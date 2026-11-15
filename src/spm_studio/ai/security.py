"""Settings and plugin-path guardrails; never use this as an OS sandbox."""
from __future__ import annotations
from pathlib import Path
import json, os, tempfile


def private_dir(path:Path) -> Path:
    path.mkdir(parents=True,exist_ok=True,mode=0o700)
    try:path.chmod(0o700)
    except OSError:pass
    return path


def atomic_json(path:Path,data:dict) -> None:
    private_dir(path.parent)
    fd,tmp=tempfile.mkstemp(prefix='.tmp-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf8') as f:
            json.dump(data,f,ensure_ascii=False,indent=2)
            f.write('\n');f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o600);os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def checked_child(parent:Path,child:Path) -> Path:
    parent=parent.expanduser().resolve()
    child=child.expanduser().resolve()
    if child==parent or parent not in child.parents:
        raise ValueError('Path outside selected workspace')
    return child


def redact(value:str) -> str:
    import re
    value=re.sub(r'(?i)(?:sk-[A-Za-z0-9_-]{12,}|AIza[A-Za-z0-9_-]{20,})','[REDACTED]',value)
    value=re.sub(r'(?im)(authorization\s*[:=]\s*bearer\s+)\S+',r'\1[REDACTED]',value)
    return value


class CredentialStore:
    """Use a real OS keyring if present; otherwise credentials exist only in RAM."""
    _volatile={}

    def __init__(self):
        self.keyring=None
        try:
            import keyring
            from keyring.backends.fail import Keyring as FailKeyring
            backend=keyring.get_keyring()
            # Never accept plaintext keyring fallbacks (keyrings.alt file backends).
            safe_modules=('keyring.backends.SecretService', 'keyring.backends.kwallet',
                          'keyring.backends.macOS', 'keyring.backends.Windows')
            if (not isinstance(backend,FailKeyring) and getattr(backend,'priority',0)>0
                    and type(backend).__module__.startswith(safe_modules)):
                self.keyring=keyring
        except Exception:pass

    def put(self,provider:str,value:str) -> str:
        key='spm-studio-ai:'+provider
        if self.keyring is not None:
            try:
                self.keyring.set_password('spm-studio-ai',provider,value)
                return 'Stored in OS keyring'
            except Exception:pass
        self._volatile[key]=value
        return 'Session-only (no secure keyring available)'

    def get(self,provider:str) -> str:
        names={'openai':'OPENAI_API_KEY','anthropic':'ANTHROPIC_API_KEY',
               'gemini':'GEMINI_API_KEY','openrouter':'OPENROUTER_API_KEY','custom':'SPM_AI_API_KEY'}
        key='spm-studio-ai:'+provider
        if key in self._volatile:return self._volatile[key]
        if self.keyring is not None:
            try:
                value=self.keyring.get_password('spm-studio-ai',provider)
                if value:return value
            except Exception:pass
        return os.getenv(names.get(provider,''),'') if provider in names else ''

    def clear(self,provider:str):
        self._volatile.pop('spm-studio-ai:'+provider,None)
        if self.keyring is not None:
            try:self.keyring.delete_password('spm-studio-ai',provider)
            except Exception:pass
