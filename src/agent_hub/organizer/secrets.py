"""Credentials of mail accounts and calendar sync (passwords, app passwords, OAuth refresh tokens, optional
OAuth client secrets) — only in the operating system's keyring (Secret Service / KWallet, macOS Keychain,
Windows Credential Manager). Without a secure keyring they live in memory for this session only, and the user
is told so. They are never written to a file, a log, an export or a prompt.
"""
from __future__ import annotations

SERVICE = 'agent-hub'
_volatile: dict[str, str] = {}


def _keyring():
    try:
        import keyring
        from keyring.backends.fail import Keyring as FailKeyring
        backend = keyring.get_keyring()
        safe = ('keyring.backends.SecretService', 'keyring.backends.kwallet', 'keyring.backends.macOS',
                'keyring.backends.Windows', 'keyring.backends.chainer')
        if isinstance(backend, FailKeyring) or getattr(backend, 'priority', 0) <= 0:
            return None
        if not type(backend).__module__.startswith(safe):
            return None
        return keyring
    except Exception:
        return None


def secure() -> bool:
    return _keyring() is not None


def put(name: str, value: str) -> str:
    """Store; returns where ('keyring' or 'session')."""
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(SERVICE, name, value)
            _volatile.pop(name, None)
            return 'keyring'
        except Exception:
            pass
    _volatile[name] = value
    return 'session'


def get(name: str) -> str:
    if name in _volatile:
        return _volatile[name]
    kr = _keyring()
    if kr is not None:
        try:
            return kr.get_password(SERVICE, name) or ''
        except Exception:
            return ''
    return ''


def delete(name: str):
    _volatile.pop(name, None)
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(SERVICE, name)
        except Exception:
            pass


def redact(text: str, *values: str) -> str:
    """Remove known secrets and token-like strings from a message before it is shown or logged."""
    import re
    out = str(text)
    for v in values:
        if v and len(v) >= 4:
            out = out.replace(v, '[hidden]')
    out = re.sub(r'(?i)(bearer\s+)[A-Za-z0-9._\-]{12,}', r'\1[hidden]', out)
    out = re.sub(r'(?i)(password|passwd|pwd|token|secret)(["\']?\s*[:=]\s*["\']?)[^\s"\',;]{3,}', r'\1\2[hidden]',
                 out)
    out = re.sub(r'ya29\.[A-Za-z0-9._\-]+|EwB[A-Za-z0-9._\-]{20,}', '[hidden]', out)
    return out
