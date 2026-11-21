"""Beta Tester client: invitation redemption, per-device session, private extension releases.

Trust model
-----------
* The invitation key is sent once per computer (``POST /v1/auth/redeem``) and never stored.
* The server answers with a per-device refresh token (kept in the OS credential store via ``keyring``; if no
  credential store is available, in ``<config>/beta_credentials.json`` readable by the user only) and a
  short-lived access token kept in memory.
* The device id is a random value created on this computer (no hardware identifier).
* Roles and access are decided by the server on every request; nothing local can grant them.
* Release manifests are signed (Ed25519) with a key pinned in ``update_config.json``; the downloaded archive
  must match the manifest's size and SHA-256 before anything is extracted (see ``extensions.py``).
* No token ever goes to GitHub, into a URL, a log or an exception message.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

KEYRING_SERVICE = 'SPM Studio beta'
TIMEOUT = 20
MAX_JSON = 2_000_000
MAX_ASSET = 200 * 1024 * 1024
OFFLINE_GRACE_DAYS = 30


class BetaError(RuntimeError):
    """``code``: INVALID_KEY, DEVICE_LIMIT_REACHED, REVOKED, EXPIRED, SUSPENDED, UNAUTHORIZED, FORBIDDEN,
    RATE_LIMITED, OFFLINE, SERVER, BAD_RESPONSE, NOT_CONFIGURED, …; ``data``: extra server fields."""

    def __init__(self, code: str, message: str, status: int = 0, data: dict | None = None):
        super().__init__(message)
        self.code, self.status, self.data = code, status, data or {}


FRIENDLY = {
    'INVALID_KEY': 'This invitation key is not valid. Check it (copy and paste it) or ask for a new one.',
    'DEVICE_LIMIT_REACHED': 'This invitation is already active on its maximum number of computers.',
    'REVOKED': 'This beta access was revoked. SPM Studio keeps working normally; ask the administrator if '
               'this is a mistake.',
    'EXPIRED': 'This invitation has expired. Ask the administrator for a renewal.',
    'SUSPENDED': 'This beta access is suspended for now.',
    'UNAUTHORIZED': 'This computer is no longer signed in to the beta. Enter your invitation key again.',
    'FORBIDDEN': 'This account is not allowed to do that.',
    'RATE_LIMITED': 'Too many attempts. Wait a few minutes and try again.',
    'OFFLINE': 'No connection to the beta service. Everything else in SPM Studio works offline.',
    'SERVER': 'The beta service has a problem right now. Try again later.',
    'BAD_RESPONSE': 'The beta service sent an unexpected answer.',
    'NOT_CONFIGURED': 'No beta service address is configured in this version of SPM Studio.',
}


def friendly(exc: Exception) -> str:
    if isinstance(exc, BetaError):
        text = FRIENDLY.get(exc.code, str(exc))
        if exc.code == 'DEVICE_LIMIT_REACHED':
            d = exc.data
            text += (f" ({d.get('active_devices', '?')} / {d.get('max_devices', '?')} computers.) Remove an old "
                     'computer from a computer that is still signed in (Settings › Beta Tester › My computers), '
                     'or ask the administrator to free a place or raise the limit.')
        return text
    return str(exc)


# ------------------------------------------------------------------ configuration & local state
def _update_config() -> dict:
    """update_config.json as shipped (beta service address, pinned extension signing keys)."""
    try:
        data = json.loads((Path(__file__).resolve().parents[1] / 'update_config.json').read_text(encoding='utf8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def api_base() -> str:
    """The beta service origin: ``SPM_STUDIO_BETA_API`` > beta.json override > update_config.json."""
    url = os.environ.get('SPM_STUDIO_BETA_API') or load_state().get('api_override') or \
        _update_config().get('beta_api', '')
    url = str(url or '').strip().rstrip('/')
    if not url:
        raise BetaError('NOT_CONFIGURED', FRIENDLY['NOT_CONFIGURED'])
    parsed = urllib.parse.urlparse(url)
    local = parsed.hostname in ('127.0.0.1', 'localhost', '::1')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and local):
        raise BetaError('NOT_CONFIGURED', 'The beta service address must use https://')
    return url


def signing_keys() -> list[bytes]:
    keys = []
    for item in _update_config().get('extension_signing_keys', []):
        try:
            raw = base64.b64decode(item)
            if len(raw) == 32:
                keys.append(raw)
        except (ValueError, TypeError):
            pass
    return keys


def _state_file() -> Path:
    from spm_studio.core import paths
    return paths.config_dir() / 'beta.json'


def load_state() -> dict:
    try:
        data = json.loads(_state_file().read_text(encoding='utf8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(**changes) -> dict:
    data = load_state()
    data.update(changes)
    for key in [k for k, v in data.items() if v is None]:
        data.pop(key)
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=1), encoding='utf8')
    tmp.replace(path)
    return data


def device_id() -> str:
    """Random id of this installation (created once, kept across updates; not derived from hardware)."""
    data = load_state()
    if not data.get('device_id'):
        data = save_state(device_id=secrets.token_hex(16))
    return data['device_id']


def default_device_label() -> str:
    import sys
    return {'win32': 'Windows PC', 'darwin': 'Mac'}.get(sys.platform, 'Linux PC')


# ------------------------------------------------------------------ credential storage
def _credential_file() -> Path:
    from spm_studio.core import paths
    return paths.config_dir() / 'beta_credentials.json'


def _keyring():
    if os.environ.get('SPM_STUDIO_BETA_NO_KEYRING'):
        return None
    try:
        import keyring
        from keyring.backends import fail
        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:
        return None


def store_refresh(token: str | None):
    """Keep (or forget, with ``None``) this computer's refresh token in the safest place available."""
    ring, user = _keyring(), device_id()
    if ring is not None:
        try:
            if token:
                ring.set_password(KEYRING_SERVICE, user, token)
            else:
                try:
                    ring.delete_password(KEYRING_SERVICE, user)
                except Exception:
                    pass
            save_state(credential_store='keyring')
            _credential_file().unlink(missing_ok=True)
            return
        except Exception:
            pass
    path = _credential_file()
    if token:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf8') as fh:
            json.dump({'refresh_token': token}, fh)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        save_state(credential_store='file')
    else:
        path.unlink(missing_ok=True)


def load_refresh() -> str:
    ring = _keyring()
    if ring is not None:
        try:
            value = ring.get_password(KEYRING_SERVICE, device_id())
            if value:
                return value
        except Exception:
            pass
    try:
        return str(json.loads(_credential_file().read_text(encoding='utf8')).get('refresh_token', ''))
    except (OSError, ValueError):
        return ''


# ------------------------------------------------------------------ HTTP
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None                                   # never follow: a token must not travel to another host


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _error_from(status: int, body: bytes) -> BetaError:
    try:
        data = json.loads(body.decode('utf8'))
        if not isinstance(data, dict):
            data = {}
    except (ValueError, UnicodeDecodeError):
        data = {}
    code = str(data.get('error') or '')
    if not code:
        code = {401: 'UNAUTHORIZED', 403: 'FORBIDDEN', 429: 'RATE_LIMITED'}.get(status,
                                                                               'SERVER' if status >= 500 else 'BAD_RESPONSE')
    message = str(data.get('message') or FRIENDLY.get(code, f'HTTP {status}'))[:300]
    return BetaError(code, message, status, data)


def request(method: str, path: str, body: dict | None = None, token: str = '', raw: bool = False,
            dest: Path | None = None, max_bytes: int = MAX_JSON):
    """One HTTPS call to the beta service. JSON in/out, or streamed into ``dest``."""
    url = api_base() + path
    data = json.dumps(body).encode('utf8') if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Accept', 'application/json')
    req.add_header('User-Agent', 'SPM-Studio-beta-client')
    if data is not None:
        req.add_header('Content-Type', 'application/json')
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    handlers = [_NoRedirect()]
    if url.startswith('https://'):
        handlers.append(urllib.request.HTTPSHandler(context=_ssl_context()))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            if 300 <= resp.status < 400:
                raise BetaError('BAD_RESPONSE', 'Unexpected redirect from the beta service', resp.status)
            if dest is not None:
                total = 0
                with open(dest, 'wb') as fh:
                    while True:
                        block = resp.read(1 << 16)
                        if not block:
                            break
                        total += len(block)
                        if total > max_bytes:
                            raise BetaError('BAD_RESPONSE', 'The download is larger than announced')
                        fh.write(block)
                return total
            payload = resp.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            raise BetaError('BAD_RESPONSE', 'Unexpected redirect from the beta service', exc.code) from None
        raise _error_from(exc.code, exc.read(MAX_JSON)) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, ssl.SSLError) as exc:
        reason = getattr(exc, 'reason', exc)
        raise BetaError('OFFLINE', f'{FRIENDLY["OFFLINE"]} ({type(reason).__name__})') from None
    if len(payload) > max_bytes:
        raise BetaError('BAD_RESPONSE', 'Answer too large')
    if raw:
        return payload
    try:
        result = json.loads(payload.decode('utf8'))
    except (ValueError, UnicodeDecodeError):
        raise BetaError('BAD_RESPONSE', FRIENDLY['BAD_RESPONSE']) from None
    if not isinstance(result, dict):
        raise BetaError('BAD_RESPONSE', FRIENDLY['BAD_RESPONSE'])
    return result


# ------------------------------------------------------------------ session
class Session:
    """The signed-in state of this computer. Thread-safe enough for one worker at a time."""

    def __init__(self):
        self.access = ''
        self.access_expires = 0.0

    # -- account
    def redeem(self, key: str, label: str = '') -> dict:
        key = ' '.join(str(key).split()).upper().replace(' ', '')
        if not key.startswith('SPM-BETA-') or len(key) < 30:
            raise BetaError('INVALID_KEY', FRIENDLY['INVALID_KEY'])
        label = (label or load_state().get('device_label') or default_device_label()).strip()[:40]
        result = request('POST', '/v1/auth/redeem', {'invitation': key, 'device_id': device_id(),
                                                     'device_label': label})
        self._accept(result)
        save_state(device_label=label)
        return result

    def _accept(self, result: dict):
        for name in ('access_token', 'refresh_token'):
            if not isinstance(result.get(name), str) or len(result[name]) < 20:
                raise BetaError('BAD_RESPONSE', FRIENDLY['BAD_RESPONSE'])
        store_refresh(result['refresh_token'])
        self.access = result['access_token']
        self.access_expires = time.time() + max(30, int(result.get('expires_in', 600))) - 20
        self._remember(result)

    @staticmethod
    def _remember(info: dict):
        account = info.get('account', info)
        save_state(status='active', role=str(account.get('role', 'tester')),
                   account_label=str(account.get('label', '') or ''),
                   active_devices=account.get('active_devices'), max_devices=account.get('max_devices'),
                   last_verified=time.time())

    def signed_in(self) -> bool:
        return bool(load_refresh())

    def refresh(self) -> str:
        token = load_refresh()
        if not token:
            raise BetaError('UNAUTHORIZED', FRIENDLY['UNAUTHORIZED'])
        try:
            result = request('POST', '/v1/auth/refresh', {'refresh_token': token, 'device_id': device_id()})
        except BetaError as exc:
            if exc.code in ('UNAUTHORIZED', 'REVOKED', 'EXPIRED', 'SUSPENDED'):
                store_refresh(None)
                save_state(status=exc.code.lower(), role=None)
            raise
        self._accept(result)
        return self.access

    def token(self) -> str:
        if not self.access or time.time() >= self.access_expires:
            self.refresh()
        return self.access

    def call(self, method: str, path: str, body: dict | None = None, **kw):
        try:
            return request(method, path, body, token=self.token(), **kw)
        except BetaError as exc:
            if exc.code == 'UNAUTHORIZED' and exc.status == 401:
                self.access = ''
                return request(method, path, body, token=self.token(), **kw)
            raise

    def me(self) -> dict:
        info = self.call('GET', '/v1/auth/me')
        self._remember(info)
        return info

    def devices(self) -> dict:
        return self.call('GET', '/v1/auth/devices')

    def rename_device(self, ident: str, label: str) -> dict:
        return self.call('PATCH', f'/v1/auth/devices/{urllib.parse.quote(ident)}', {'label': label[:40]})

    def remove_device(self, ident: str) -> dict:
        result = self.call('DELETE', f'/v1/auth/devices/{urllib.parse.quote(ident)}')
        if ident == device_id():
            self.forget()
        return result

    def logout(self, unlink: bool = False):
        """Sign this computer out. ``unlink=True`` also frees its place in the device limit."""
        try:
            if unlink:
                self.call('DELETE', f'/v1/auth/devices/{urllib.parse.quote(device_id())}')
            else:
                self.call('POST', '/v1/auth/logout', {})
        finally:
            self.forget()

    def forget(self):
        store_refresh(None)
        self.access = ''
        save_state(status='not_activated', role=None, account_label=None, active_devices=None, max_devices=None,
                   last_verified=None)

    # -- private releases
    def latest_release(self) -> dict:
        from . import extensions
        result = self.call('GET', '/v1/beta/releases/latest')
        manifest = extensions.verify_manifest(result.get('manifest'), result.get('signature', ''), signing_keys())
        save_state(last_release_check=time.time())
        return manifest

    def download(self, manifest: dict) -> Path:
        from . import extensions
        folder = extensions.downloads_dir()
        target = folder / f'download-{secrets.token_hex(8)}.zip'
        size = int(manifest['artifact']['size'])
        try:
            self.call('GET', manifest['artifact']['download_path'], dest=target, max_bytes=min(size, MAX_ASSET))
            extensions.check_artifact(target, manifest)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return target


def offline_grace_ok(state: dict | None = None) -> bool:
    """Installed private extensions keep running while the last successful check is recent enough."""
    state = state if state is not None else load_state()
    if state.get('status') in ('revoked', 'expired', 'suspended', 'unauthorized', 'not_activated'):
        return False
    return time.time() - float(state.get('last_verified', 0) or 0) < OFFLINE_GRACE_DAYS * 86400
