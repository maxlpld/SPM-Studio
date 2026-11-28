"""OAuth 2.0 for Gmail / Google Calendar and Microsoft 365 / Outlook (Graph), with the user's **own** OAuth
client id (see ``docs/EMAIL_CALENDAR_OAUTH.md``). Authorization code flow with PKCE and a loopback redirect
(``http://127.0.0.1:<random port>``), the method Google and Microsoft document for desktop apps.

* No client id or secret ships with Agent Hub. The client id is a setting; a Google "Desktop app" client also
  has a client secret, which Google states is not confidential for installed apps — it is still kept only in
  the keyring (``oauth-secret:google``), never in a file.
* Refresh tokens: keyring only (``oauth-refresh:<provider>:<account id>``). Access tokens: memory only.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets as _secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from . import secrets

PROVIDERS = {
    'google': {'auth': 'https://accounts.google.com/o/oauth2/v2/auth',
               'token': 'https://oauth2.googleapis.com/token',
               'mail_scopes': ['https://mail.google.com/'],
               'calendar_scopes': ['https://www.googleapis.com/auth/calendar'],
               'extra': {'access_type': 'offline', 'prompt': 'consent'}},
    'microsoft': {'auth': 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize',
                  'token': 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token',
                  'mail_scopes': ['offline_access', 'Mail.ReadWrite', 'Mail.Send', 'User.Read'],
                  'calendar_scopes': ['offline_access', 'Calendars.ReadWrite', 'User.Read'],
                  'extra': {'prompt': 'select_account'}},
}
_tokens: dict[str, tuple[str, float]] = {}


def client_id(provider: str, account: dict | None = None) -> str:
    from_account = ((account or {}).get('oauth') or {}).get('client_id', '')
    return from_account or secrets.get(f'oauth-client:{provider}')


def _endpoints(provider: str, account: dict | None):
    meta = PROVIDERS[provider]
    tenant = ((account or {}).get('oauth') or {}).get('tenant') or 'common'
    return meta['auth'].format(tenant=tenant), meta['token'].format(tenant=tenant)


def refresh_key(provider: str, account_id: str) -> str:
    return f'oauth-refresh:{provider}:{account_id}'


def authorize(provider: str, account: dict, scopes: list[str], open_browser=None, timeout: int = 300) -> dict:
    """Interactive sign-in in the browser. Stores the refresh token; returns {'scopes', 'expires_in'}."""
    cid = client_id(provider, account)
    if not cid:
        raise ValueError('Enter your OAuth client id first (see the guide in the settings page)')
    verifier = base64.urlsafe_b64encode(_secrets.token_bytes(48)).rstrip(b'=').decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    state = _secrets.token_urlsafe(16)
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = parse_qs(urlparse(self.path).query)
            if q.get('state', [''])[0] == state:
                result['code'] = q.get('code', [''])[0]
                result['error'] = q.get('error', [''])[0]
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write('<html><body style="font-family:sans-serif"><h3>Agent Hub</h3><p>You can close this '
                             'tab and go back to the app.</p></body></html>'.encode())

        def log_message(self, *_a):
            return

    server = HTTPServer(('127.0.0.1', 0), Handler)
    redirect = f'http://127.0.0.1:{server.server_port}'
    auth_url, token_url = _endpoints(provider, account)
    params = {'client_id': cid, 'redirect_uri': redirect, 'response_type': 'code', 'scope': ' '.join(scopes),
              'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256',
              **PROVIDERS[provider]['extra']}
    if account.get('address'):
        params['login_hint'] = account['address']
    url = auth_url + '?' + urlencode(params)
    thread = threading.Thread(target=lambda: _serve_until(server, result, timeout), daemon=True)
    thread.start()
    if open_browser is None:
        import webbrowser
        open_browser = webbrowser.open
    open_browser(url)
    thread.join(timeout + 5)
    server.server_close()
    if result.get('error') or not result.get('code'):
        raise RuntimeError('Sign-in was cancelled or refused' + (f" ({result['error']})" if result.get('error') else ''))
    body = {'client_id': cid, 'code': result['code'], 'redirect_uri': redirect, 'grant_type': 'authorization_code',
            'code_verifier': verifier}
    client_secret = secrets.get(f'oauth-secret:{provider}')
    if client_secret:
        body['client_secret'] = client_secret
    data = _post(token_url, body)
    if data.get('refresh_token'):
        secrets.put(refresh_key(provider, account['id']), data['refresh_token'])
    if data.get('access_token'):
        _tokens[f"{provider}:{account['id']}"] = (data['access_token'], time.time() + int(data.get('expires_in', 3000)))
    return {'scopes': data.get('scope', ''), 'expires_in': data.get('expires_in')}


def _serve_until(server, result, timeout):
    server.timeout = 1
    end = time.time() + timeout
    while time.time() < end and 'code' not in result:
        server.handle_request()


def _post(url: str, body: dict) -> dict:
    req = Request(url, data=urlencode(body).encode(), method='POST',
                  headers={'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode('utf8'))
    except Exception as exc:
        detail = ''
        try:
            detail = exc.read().decode('utf8', 'replace')[:300]          # type: ignore[attr-defined]
        except Exception:
            pass
        raise RuntimeError('Token request failed: ' + secrets.redact(detail or str(exc))) from None


def access_token(provider: str, account: dict) -> str:
    key = f"{provider}:{account['id']}"
    token, expires = _tokens.get(key, ('', 0))
    if token and expires > time.time() + 60:
        return token
    refresh = secrets.get(refresh_key(provider, account['id']))
    if not refresh:
        raise RuntimeError('Not signed in: use “Sign in” in the account settings')
    _auth, token_url = _endpoints(provider, account)
    body = {'client_id': client_id(provider, account), 'grant_type': 'refresh_token', 'refresh_token': refresh}
    client_secret = secrets.get(f'oauth-secret:{provider}')
    if client_secret:
        body['client_secret'] = client_secret
    data = _post(token_url, body)
    if data.get('refresh_token') and data['refresh_token'] != refresh:
        secrets.put(refresh_key(provider, account['id']), data['refresh_token'])
    _tokens[key] = (data['access_token'], time.time() + int(data.get('expires_in', 3000)))
    return data['access_token']


def sign_out(provider: str, account_id: str):
    secrets.delete(refresh_key(provider, account_id))
    _tokens.pop(f'{provider}:{account_id}', None)
