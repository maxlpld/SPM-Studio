"""E-mail (Qt-free): accounts (IMAP/SMTP with presets and app passwords, optional OAuth for Gmail and
Microsoft 365 / Outlook through Microsoft Graph), reading, searching, and an **outbox that only the user can
release**.

Sending rule (enforced here, not in a prompt):

* Nothing in this module sends, replies, forwards or moves mail except :meth:`Outbox.execute`, and it needs a
  one-time :class:`Ticket` from :meth:`Outbox.approve`.
* :meth:`Outbox.approve` needs the SHA-256 digest of the exact message shown to the user (recipients, subject,
  body, attachment names and bytes). Editing the draft changes the digest, so an approval never covers text the
  user did not see. A ticket is single-use and expires after 10 minutes.
* Tickets are signed with a key that exists only in this process (``_KEY``). Assistant tools
  (``organizer.tools``) can only *propose* (:meth:`Outbox.propose`); they never receive a ticket. Full access,
  automatic modes and "Always allow" rules have no influence on any of this.

Account fields (``mail_accounts.json``, no secrets): ``id, label, address, kind (imap · gmail · microsoft),
imap {host, port, security}, smtp {host, port, security}, username, folders, poll_minutes, idle, enabled,
oauth {client_id, tenant}``. The password / app password / refresh token is in the keyring under
``mail:<id>``; an optional OAuth client secret under ``oauth-secret:<provider>``.
"""
from __future__ import annotations

import base64
import datetime as dt
import email
import email.policy
import hashlib
import hmac
import json
import mimetypes
import re
import secrets as _secrets
import time
from email.message import EmailMessage
from email.utils import formataddr, getaddresses, make_msgid, parsedate_to_datetime
from pathlib import Path

from . import secrets
from .base import atomic_write, new_id, now_iso, read_json

PRESETS = {
    'gmail': {'label': 'Gmail', 'imap': {'host': 'imap.gmail.com', 'port': 993, 'security': 'ssl'},
              'smtp': {'host': 'smtp.gmail.com', 'port': 465, 'security': 'ssl'},
              'hint': 'Turn on 2-step verification, then create an app password at myaccount.google.com/apppasswords '
                      '(or use “Sign in with Google”, see docs/EMAIL_OAUTH.md).'},
    'outlook': {'label': 'Outlook.com / Hotmail', 'imap': {'host': 'outlook.office365.com', 'port': 993,
                                                           'security': 'ssl'},
                'smtp': {'host': 'smtp-mail.outlook.com', 'port': 587, 'security': 'starttls'},
                'hint': 'Microsoft accounts usually need “Sign in with Microsoft” (OAuth); app passwords work when '
                        'two-step verification is on.'},
    'office365': {'label': 'Microsoft 365 (work / school)', 'imap': {'host': 'outlook.office365.com', 'port': 993,
                                                                     'security': 'ssl'},
                  'smtp': {'host': 'smtp.office365.com', 'port': 587, 'security': 'starttls'},
                  'hint': 'Most organisations require “Sign in with Microsoft” (OAuth).'},
    'icloud': {'label': 'iCloud Mail', 'imap': {'host': 'imap.mail.me.com', 'port': 993, 'security': 'ssl'},
               'smtp': {'host': 'smtp.mail.me.com', 'port': 587, 'security': 'starttls'},
               'hint': 'Create an app-specific password at appleid.apple.com › Sign-In and Security.'},
    'yahoo': {'label': 'Yahoo Mail', 'imap': {'host': 'imap.mail.yahoo.com', 'port': 993, 'security': 'ssl'},
              'smtp': {'host': 'smtp.mail.yahoo.com', 'port': 465, 'security': 'ssl'},
              'hint': 'Generate an app password in Yahoo Account Security.'},
    'gmx': {'label': 'GMX', 'imap': {'host': 'imap.gmx.net', 'port': 993, 'security': 'ssl'},
            'smtp': {'host': 'mail.gmx.net', 'port': 587, 'security': 'starttls'}, 'hint': 'Enable IMAP in GMX settings.'},
    'fastmail': {'label': 'Fastmail', 'imap': {'host': 'imap.fastmail.com', 'port': 993, 'security': 'ssl'},
                 'smtp': {'host': 'smtp.fastmail.com', 'port': 465, 'security': 'ssl'},
                 'hint': 'Use an app password (Settings › Privacy & Security).'},
    'custom': {'label': 'Other (university, work, own server)', 'imap': {'host': '', 'port': 993, 'security': 'ssl'},
               'smtp': {'host': '', 'port': 587, 'security': 'starttls'},
               'hint': 'Ask your IT service for the IMAP and SMTP server names; ports 993 and 587 are usual.'},
}
ACTIONS = ('send', 'reply', 'forward', 'move')
TICKET_SECONDS = 600
MAX_ATTACHMENT_BYTES = 25 * 2 ** 20
_KEY = _secrets.token_bytes(32)              # exists only in this process; never stored


class ApprovalError(PermissionError):
    """Raised whenever something tries to send or move mail without the user's approval."""


# ======================================================================================== accounts
class MailStore:
    """Accounts, a small header cache, processed messages, and the outbox."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.accounts_path = self.root / 'mail_accounts.json'
        self.cache_path = self.root / 'mail_cache.json'
        self.outbox = Outbox(self.root / 'mail_outbox.json', self)

    # ---- accounts
    def accounts(self) -> list[dict]:
        data = read_json(self.accounts_path, {})
        return [a for a in (data.get('accounts') or []) if isinstance(a, dict) and a.get('id')]

    def connected(self) -> list[dict]:
        return [a for a in self.accounts() if a.get('enabled', True)]

    def account(self, aid: str) -> dict | None:
        return next((a for a in self.accounts() if a['id'] == aid), None)

    def _save_accounts(self, accounts: list[dict]):
        atomic_write(self.accounts_path, {'schema': 1, 'accounts': accounts})

    def add_account(self, fields: dict, password: str = '') -> dict:
        preset = PRESETS.get(fields.get('preset') or 'custom', PRESETS['custom'])
        acc = {'id': new_id('m'), 'label': '', 'address': '', 'kind': 'imap', 'preset': fields.get('preset', 'custom'),
               'imap': dict(preset['imap']), 'smtp': dict(preset['smtp']), 'username': '',
               'folders': ['INBOX'], 'poll_minutes': 5, 'idle': True, 'enabled': True, 'oauth': {},
               'sent_folder': '', 'admin_detection': True}
        for key in ('label', 'address', 'kind', 'imap', 'smtp', 'username', 'folders', 'poll_minutes', 'idle',
                    'enabled', 'oauth', 'sent_folder', 'admin_detection'):
            if key in fields and fields[key] not in (None, ''):
                acc[key] = fields[key]
        acc['address'] = str(acc['address']).strip()
        if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', acc['address']):
            raise ValueError('Enter the e-mail address of the account')
        acc['label'] = acc['label'] or acc['address']
        acc['username'] = acc['username'] or acc['address']
        acc['poll_minutes'] = max(1, min(240, int(acc['poll_minutes'])))
        if acc['kind'] == 'imap' and not (acc['imap'].get('host') and acc['smtp'].get('host')):
            raise ValueError('Enter the IMAP and SMTP servers (or choose a provider)')
        accounts = self.accounts() + [acc]
        self._save_accounts(accounts)
        if password:
            secrets.put('mail:' + acc['id'], password)
        return acc

    def update_account(self, aid: str, **fields) -> dict:
        accounts = self.accounts()
        for a in accounts:
            if a['id'] == aid:
                for key in ('label', 'imap', 'smtp', 'username', 'folders', 'poll_minutes', 'idle', 'enabled',
                            'oauth', 'sent_folder', 'admin_detection'):
                    if key in fields:
                        a[key] = fields[key]
                self._save_accounts(accounts)
                return a
        raise KeyError(aid)

    def remove_account(self, aid: str):
        self._save_accounts([a for a in self.accounts() if a['id'] != aid])
        secrets.delete('mail:' + aid)

    @staticmethod
    def set_secret(aid: str, value: str) -> str:
        return secrets.put('mail:' + aid, value)

    # ---- cache (headers + short previews only, for the list and the assistant's search)
    def cache(self) -> dict:
        data = read_json(self.cache_path, {})
        data.setdefault('messages', {})
        data.setdefault('processed', {})
        return data

    def remember(self, messages: list[dict]):
        data = self.cache()
        for m in messages:
            key = f"{m['account']}|{m['folder']}|{m['uid']}"
            data['messages'][key] = {k: m.get(k) for k in ('account', 'folder', 'uid', 'message_id', 'from', 'to',
                                                            'subject', 'date', 'snippet', 'flags', 'attachments')}
        items = sorted(data['messages'].items(), key=lambda kv: str(kv[1].get('date') or ''), reverse=True)[:3000]
        data['messages'] = dict(items)
        atomic_write(self.cache_path, data)

    def cached(self, account: str = '', query: str = '', limit: int = 50) -> list[dict]:
        q = str(query or '').lower()
        out = [m for m in self.cache()['messages'].values() if (not account or m.get('account') == account) and
               (not q or q in str(m.get('subject', '')).lower() or q in str(m.get('from', '')).lower() or
                q in str(m.get('snippet', '')).lower())]
        out.sort(key=lambda m: str(m.get('date') or ''), reverse=True)
        return out[:limit]

    def processed(self, key: str) -> bool:
        return key in self.cache()['processed']

    def mark_processed(self, key: str, result: str = ''):
        data = self.cache()
        data['processed'][key] = {'at': now_iso(), 'result': result[:200]}
        atomic_write(self.cache_path, data)

    # ---- reading (network; call from a worker thread)
    def client(self, aid: str) -> 'MailClient':
        acc = self.account(aid)
        if acc is None:
            raise KeyError(aid)
        if acc['kind'] == 'microsoft':
            return GraphClient(acc)
        return ImapClient(acc)


# ======================================================================================== messages
def parse_message(raw: bytes, account: str = '', folder: str = '', uid: str = '', flags=()) -> dict:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    body, html_body, attachments = '', '', []
    for part in msg.walk() if msg.is_multipart() else [msg]:
        disposition = (part.get_content_disposition() or '').lower()
        ctype = part.get_content_type()
        if part.is_multipart():
            continue
        if disposition == 'attachment' or (part.get_filename() and disposition != 'inline'):
            payload = part.get_payload(decode=True) or b''
            attachments.append({'name': part.get_filename() or 'attachment', 'type': ctype, 'size': len(payload),
                                'index': len(attachments)})
            continue
        if ctype == 'text/plain' and not body:
            try:
                body = part.get_content()
            except (LookupError, UnicodeDecodeError):
                body = (part.get_payload(decode=True) or b'').decode('utf8', 'replace')
        elif ctype == 'text/html' and not html_body:
            try:
                html_body = part.get_content()
            except (LookupError, UnicodeDecodeError):
                html_body = (part.get_payload(decode=True) or b'').decode('utf8', 'replace')
    if not body and html_body:
        body = html_to_text(html_body)
    try:
        date = parsedate_to_datetime(msg.get('Date')).astimezone().replace(tzinfo=None).isoformat(timespec='seconds')
    except (TypeError, ValueError, IndexError):
        date = ''
    return {'account': account, 'folder': folder, 'uid': str(uid), 'message_id': str(msg.get('Message-ID', '')),
            'from': str(msg.get('From', '')), 'to': str(msg.get('To', '')), 'cc': str(msg.get('Cc', '')),
            'reply_to': str(msg.get('Reply-To', '')), 'subject': str(msg.get('Subject', '')), 'date': date,
            'references': str(msg.get('References', '')), 'body': body[:200000], 'html': bool(html_body),
            'snippet': re.sub(r'\s+', ' ', body)[:240], 'attachments': attachments, 'flags': list(flags)}


def attachment_bytes(raw: bytes, index: int) -> tuple[str, bytes]:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    found = 0
    for part in msg.walk():
        if part.is_multipart():
            continue
        disposition = (part.get_content_disposition() or '').lower()
        if disposition == 'attachment' or (part.get_filename() and disposition != 'inline'):
            if found == index:
                return part.get_filename() or 'attachment', part.get_payload(decode=True) or b''
            found += 1
    raise IndexError(index)


def html_to_text(html_text: str) -> str:
    import html as _html
    text = re.sub(r'(?is)<(script|style).*?</\1>', ' ', html_text)
    text = re.sub(r'(?i)<br\s*/?>|</p>|</div>|</li>|</tr>', '\n', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = _html.unescape(text)
    return re.sub(r'[ \t]+', ' ', re.sub(r'\n\s*\n+', '\n\n', text)).strip()


def addresses(text: str) -> list[str]:
    return [a for _n, a in getaddresses([str(text or '')]) if '@' in a]


# ======================================================================================== outbox
class Ticket:
    __slots__ = ('item_id', 'digest', 'nonce', 'expires', 'signature')

    def __init__(self, item_id, digest, nonce, expires, signature):
        self.item_id, self.digest, self.nonce, self.expires, self.signature = item_id, digest, nonce, expires, signature


def _sign(item_id: str, digest: str, nonce: str, expires: float) -> str:
    return hmac.new(_KEY, f'{item_id}|{digest}|{nonce}|{expires:.0f}'.encode(), hashlib.sha256).hexdigest()


def draft_digest(item: dict) -> str:
    """SHA-256 over what the user sees and what would leave: action, account, recipients, subject, body,
    attachment names and contents, target folder."""
    d = item.get('draft') or {}
    h = hashlib.sha256()
    for key in ('to', 'cc', 'bcc'):
        h.update(key.encode() + b'\0' + ','.join(sorted(addresses(','.join(d.get(key) or [])
                                                                   if isinstance(d.get(key), list) else
                                                                   d.get(key) or ''))).encode() + b'\0')
    for key in ('subject', 'body', 'in_reply_to', 'folder', 'uid', 'source_folder'):
        h.update(key.encode() + b'\0' + str(d.get(key) or '').encode('utf8') + b'\0')
    h.update(str(item.get('action')).encode() + b'\0' + str(item.get('account')).encode() + b'\0')
    for path in d.get('attachments') or []:
        p = Path(path)
        h.update(p.name.encode() + b'\0')
        try:
            h.update(hashlib.sha256(p.read_bytes()).digest())
        except OSError:
            h.update(b'missing')
    return h.hexdigest()


class Outbox:
    """Drafts waiting for the user: ``propose`` → (``edit``) → ``approve`` (user click) → ``execute``."""

    def __init__(self, path: Path, store: MailStore):
        self.path = Path(path)
        self.store = store
        self._used: set[str] = set()
        self.transport = None                      # tests may replace the delivery function

    def _load(self) -> dict:
        data = read_json(self.path, {})
        data.setdefault('items', {})
        return data

    def _save(self, data: dict):
        atomic_write(self.path, data)

    def items(self, status: str | None = 'pending') -> list[dict]:
        out = [i for i in self._load()['items'].values() if status is None or i.get('status') == status]
        out.sort(key=lambda i: i.get('created', ''))
        return out

    def get(self, item_id: str) -> dict | None:
        return self._load()['items'].get(item_id)

    def propose(self, action: str, account: str, draft: dict, origin: str = 'assistant', note: str = '') -> dict:
        """A pending item. This never sends anything."""
        if action not in ACTIONS:
            raise ValueError(f'Unknown mail action {action!r}')
        if self.store.account(account) is None:
            accounts = self.store.connected()
            if not accounts:
                raise ValueError('No e-mail account is connected (Agent Hub › Settings › E-mail)')
            account = accounts[0]['id']
        clean = self._clean_draft(action, draft)
        item = {'id': new_id('o'), 'action': action, 'account': account, 'draft': clean, 'origin': origin,
                'note': str(note)[:500], 'status': 'pending', 'created': now_iso(), 'history': []}
        item['digest'] = draft_digest(item)
        data = self._load()
        data['items'][item['id']] = item
        self._save(data)
        return item

    @staticmethod
    def _clean_draft(action: str, draft: dict) -> dict:
        d = {k: draft.get(k) for k in ('to', 'cc', 'bcc', 'subject', 'body', 'attachments', 'in_reply_to',
                                       'references', 'folder', 'uid', 'source_folder', 'quoted') if k in draft}
        for key in ('to', 'cc', 'bcc'):
            value = d.get(key) or []
            if isinstance(value, str):
                value = [a.strip() for a in re.split(r'[,;]', value) if a.strip()]
            d[key] = [str(a)[:320] for a in value][:100]
        d['subject'] = str(d.get('subject') or '')[:998].replace('\r', ' ').replace('\n', ' ')
        d['body'] = str(d.get('body') or '')[:500000]
        files = []
        for path in d.get('attachments') or []:
            p = Path(str(path)).expanduser()
            if not p.is_file():
                raise ValueError(f'Attachment not found: {p.name}')
            if p.stat().st_size > MAX_ATTACHMENT_BYTES:
                raise ValueError(f'Attachment too large: {p.name}')
            files.append(str(p.resolve()))
        d['attachments'] = files
        if action in ('send', 'reply', 'forward') and not (d['to'] or d['cc'] or d['bcc']):
            raise ValueError('The message has no recipient')
        if action == 'move' and not (d.get('folder') and d.get('uid')):
            raise ValueError('Moving needs the message and the target folder')
        return d

    def edit(self, item_id: str, **fields) -> dict:
        """The user changed the draft (Edit): the old digest — and any approval — no longer applies."""
        data = self._load()
        item = data['items'][item_id]
        if item['status'] != 'pending':
            raise ValueError('Only a waiting message can be edited')
        draft = dict(item['draft'], **{k: v for k, v in fields.items() if k in ('to', 'cc', 'bcc', 'subject', 'body',
                                                                                 'attachments', 'folder')})
        item['draft'] = self._clean_draft(item['action'], draft)
        item['digest'] = draft_digest(item)
        item['history'].append({'at': now_iso(), 'what': 'edited by the user'})
        self._save(data)
        return item

    def discard(self, item_id: str) -> dict:
        data = self._load()
        item = data['items'][item_id]
        item['status'] = 'discarded'
        item['history'].append({'at': now_iso(), 'what': 'discarded by the user'})
        self._save(data)
        return item

    def approve(self, item_id: str, shown_digest: str) -> Ticket:
        """The user pressed *Send* on the card that showed the message with ``shown_digest``."""
        item = self.get(item_id)
        if item is None or item['status'] != 'pending':
            raise ApprovalError('This message is not waiting for approval')
        current = draft_digest(item)
        if not hmac.compare_digest(current, str(shown_digest)) or current != item['digest']:
            raise ApprovalError('The message changed after it was shown: review it again')
        nonce = _secrets.token_hex(12)
        expires = time.time() + TICKET_SECONDS
        return Ticket(item_id, current, nonce, expires, _sign(item_id, current, nonce, expires))

    def execute(self, ticket) -> dict:
        """Send / reply / forward / move the approved item. Anything without a valid ticket is refused."""
        if not isinstance(ticket, Ticket):
            raise ApprovalError('Sending needs the user\'s approval (no ticket)')
        if not hmac.compare_digest(ticket.signature, _sign(ticket.item_id, ticket.digest, ticket.nonce,
                                                            ticket.expires)):
            raise ApprovalError('Invalid approval')
        if ticket.expires < time.time():
            raise ApprovalError('The approval expired: press Send again')
        if ticket.nonce in self._used:
            raise ApprovalError('This approval was already used')
        item = self.get(ticket.item_id)
        if item is None or item['status'] != 'pending' or draft_digest(item) != ticket.digest:
            raise ApprovalError('The message changed after approval')
        self._used.add(ticket.nonce)
        data = self._load()
        data['items'][item['id']]['status'] = 'sending'
        self._save(data)
        try:
            result = (self.transport or _deliver)(self.store, item)
        except Exception as exc:
            data = self._load()
            data['items'][item['id']]['status'] = 'pending'
            data['items'][item['id']]['history'].append({'at': now_iso(), 'what': 'failed: ' + secrets.redact(str(exc))[:300]})
            data['items'][item['id']]['digest'] = draft_digest(data['items'][item['id']])
            self._save(data)
            raise
        data = self._load()
        done = data['items'][item['id']]
        done['status'] = 'done'
        done['done'] = now_iso()
        done['history'].append({'at': now_iso(), 'what': f"{item['action']} approved by the user"})
        self._save(data)
        return dict(done, result=result)


def build_mime(account: dict, item: dict) -> EmailMessage:
    d = item['draft']
    msg = EmailMessage()
    msg['From'] = formataddr((account.get('display_name') or '', account['address']))
    if d.get('to'):
        msg['To'] = ', '.join(d['to'])
    if d.get('cc'):
        msg['Cc'] = ', '.join(d['cc'])
    msg['Subject'] = d.get('subject') or ''
    msg['Date'] = email.utils.formatdate(localtime=True)
    msg['Message-ID'] = make_msgid(domain=account['address'].split('@')[-1])
    if d.get('in_reply_to'):
        msg['In-Reply-To'] = d['in_reply_to']
        msg['References'] = ((d.get('references') or '') + ' ' + d['in_reply_to']).strip()
    msg.set_content(d.get('body') or '')
    for path in d.get('attachments') or []:
        p = Path(path)
        ctype = mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
        main, sub = ctype.split('/', 1)
        msg.add_attachment(p.read_bytes(), maintype=main, subtype=sub, filename=p.name)
    return msg


def _deliver(store: MailStore, item: dict) -> str:
    """The only place that hands a message to a server. Called by ``Outbox.execute`` alone."""
    account = store.account(item['account'])
    if account is None:
        raise ValueError('The account was removed')
    client = store.client(account['id'])
    if item['action'] == 'move':
        client.move(item['draft']['uid'], item['draft'].get('source_folder') or 'INBOX', item['draft']['folder'])
        return 'moved'
    message = build_mime(account, item)
    recipients = addresses(','.join(item['draft'].get('to', []) + item['draft'].get('cc', []) +
                                    item['draft'].get('bcc', [])))
    client.send(message, recipients)
    return 'sent'


# ======================================================================================== transports
class MailClient:
    def __init__(self, account: dict):
        self.account = account

    def secret(self) -> str:
        return secrets.get('mail:' + self.account['id'])


class ImapClient(MailClient):
    """IMAP (read, search, move) + SMTP (send). Password / app password or OAuth (XOAUTH2, Gmail)."""

    def _auth_string(self) -> str:
        from .oauth import access_token
        token = access_token('google', self.account)
        return f"user={self.account['username']}\x01auth=Bearer {token}\x01\x01"

    def imap(self):
        import imaplib
        import ssl
        cfg = self.account['imap']
        ctx = ssl.create_default_context()
        if cfg.get('security', 'ssl') == 'ssl':
            conn = imaplib.IMAP4_SSL(cfg['host'], int(cfg.get('port') or 993), ssl_context=ctx, timeout=30)
        else:
            conn = imaplib.IMAP4(cfg['host'], int(cfg.get('port') or 143), timeout=30)
            if cfg.get('security') == 'starttls':
                conn.starttls(ssl_context=ctx)
        try:
            if self.account['kind'] == 'gmail':
                auth = self._auth_string()
                conn.authenticate('XOAUTH2', lambda _c: auth.encode())
            else:
                conn.login(self.account['username'], self.secret())
        except imaplib.IMAP4.error as exc:
            raise RuntimeError('Sign-in refused by the mail server: ' + secrets.redact(str(exc), self.secret()))
        return conn

    def folders(self) -> list[str]:
        conn = self.imap()
        try:
            typ, data = conn.list()
            out = []
            for line in data or []:
                text = line.decode('utf8', 'replace') if isinstance(line, bytes) else str(line)
                m = re.search(r'"([^"]*)"\s*$|\s(\S+)\s*$', text)
                if m:
                    out.append((m.group(1) or m.group(2)).strip('"'))
            return out
        finally:
            _logout(conn)

    def recent(self, folder: str = 'INBOX', days: int = 7, limit: int = 50, unseen_only: bool = False) -> list[dict]:
        conn = self.imap()
        try:
            conn.select(_quote(folder), readonly=True)
            since = (dt.date.today() - dt.timedelta(days=days)).strftime('%d-%b-%Y')
            criteria = ['SINCE', since] + (['UNSEEN'] if unseen_only else [])
            typ, data = conn.uid('SEARCH', None, *criteria)
            uids = (data[0] or b'').split()[-limit:]
            return self._fetch(conn, folder, uids)
        finally:
            _logout(conn)

    def search(self, query: str, folder: str = 'INBOX', limit: int = 30) -> list[dict]:
        conn = self.imap()
        try:
            conn.select(_quote(folder), readonly=True)
            q = str(query).replace('"', '')
            typ, data = conn.uid('SEARCH', 'CHARSET', 'UTF-8', 'OR', 'SUBJECT', f'"{q}"',
                                 'OR', 'FROM', f'"{q}"', 'BODY', f'"{q}"')
            uids = (data[0] or b'').split()[-limit:]
            return self._fetch(conn, folder, uids)
        finally:
            _logout(conn)

    def _fetch(self, conn, folder, uids) -> list[dict]:
        out = []
        for uid in reversed(uids):
            typ, data = conn.uid('FETCH', uid, '(FLAGS BODY.PEEK[])')
            raw, flags = b'', []
            for part in data or []:
                if isinstance(part, tuple):
                    raw = part[1]
                    flags = re.findall(rb'\\(\w+)', part[0])
            if raw:
                out.append(parse_message(raw, self.account['id'], folder, uid.decode(),
                                         [f.decode() for f in flags]))
        return out

    def raw(self, uid: str, folder: str = 'INBOX') -> bytes:
        conn = self.imap()
        try:
            conn.select(_quote(folder), readonly=True)
            typ, data = conn.uid('FETCH', str(uid), '(BODY.PEEK[])')
            for part in data or []:
                if isinstance(part, tuple):
                    return part[1]
            raise KeyError(uid)
        finally:
            _logout(conn)

    def message(self, uid: str, folder: str = 'INBOX') -> dict:
        return parse_message(self.raw(uid, folder), self.account['id'], folder, uid)

    def idle_wait(self, folder: str = 'INBOX', seconds: int = 600) -> bool:
        """Wait for new mail with IMAP IDLE (Python ≥ 3.14); False when not supported."""
        conn = self.imap()
        try:
            if not hasattr(conn, 'idle') or b'IDLE' not in b' '.join(getattr(conn, 'capabilities', ()) or ()):
                return False
            conn.select(_quote(folder), readonly=True)
            with conn.idle(duration=seconds) as idler:
                for _resp in idler:
                    return True
            return True
        except Exception:
            return False
        finally:
            _logout(conn)

    # ---- the two actions that need a ticket; only reached through Outbox.execute → _deliver
    def move(self, uid: str, source: str, target: str):
        conn = self.imap()
        try:
            conn.select(_quote(source))
            typ, _ = conn.uid('MOVE', str(uid), _quote(target))
            if typ != 'OK':
                conn.uid('COPY', str(uid), _quote(target))
                conn.uid('STORE', str(uid), '+FLAGS', '(\\Deleted)')
                conn.expunge()
        finally:
            _logout(conn)

    def send(self, message: EmailMessage, recipients: list[str]):
        import smtplib
        import ssl
        cfg = self.account['smtp']
        ctx = ssl.create_default_context()
        if cfg.get('security') == 'ssl':
            server = smtplib.SMTP_SSL(cfg['host'], int(cfg.get('port') or 465), context=ctx, timeout=60)
        else:
            server = smtplib.SMTP(cfg['host'], int(cfg.get('port') or 587), timeout=60)
            if cfg.get('security', 'starttls') == 'starttls':
                server.starttls(context=ctx)
        try:
            if self.account['kind'] == 'gmail':
                auth = base64.b64encode(self._auth_string().encode()).decode()
                code, resp = server.docmd('AUTH', 'XOAUTH2 ' + auth)
                if code != 235:
                    raise RuntimeError('Sign-in refused by the mail server')
            else:
                server.login(self.account['username'], self.secret())
            server.send_message(message, to_addrs=recipients)
        finally:
            try:
                server.quit()
            except Exception:
                pass


class GraphClient(MailClient):
    """Microsoft 365 / Outlook through Microsoft Graph (OAuth with the user's own client id)."""
    BASE = 'https://graph.microsoft.com/v1.0'

    def _request(self, method: str, path: str, body=None, params: dict | None = None):
        from urllib.parse import urlencode
        from urllib.request import Request, urlopen
        from .oauth import access_token
        token = access_token('microsoft', self.account)
        url = self.BASE + path + ('?' + urlencode(params) if params else '')
        data = json.dumps(body).encode() if body is not None else None
        req = Request(url, data=data, method=method, headers={'Authorization': 'Bearer ' + token,
                                                              'Content-Type': 'application/json'})
        with urlopen(req, timeout=60) as resp:
            text = resp.read().decode('utf8')
        return json.loads(text) if text else {}

    def _parse(self, m: dict, folder: str) -> dict:
        body = (m.get('body') or {}).get('content', '') or m.get('bodyPreview', '')
        if (m.get('body') or {}).get('contentType') == 'html':
            body = html_to_text(body)
        sender = (m.get('from') or {}).get('emailAddress') or {}
        to = ', '.join(r['emailAddress'].get('address', '') for r in m.get('toRecipients') or [])
        return {'account': self.account['id'], 'folder': folder, 'uid': m.get('id', ''),
                'message_id': m.get('internetMessageId', ''),
                'from': formataddr((sender.get('name', ''), sender.get('address', ''))), 'to': to, 'cc': '',
                'subject': m.get('subject', ''), 'date': str(m.get('receivedDateTime', ''))[:19], 'body': body,
                'snippet': m.get('bodyPreview', '')[:240], 'attachments': [], 'flags': [] if not m.get('isRead')
                else ['Seen'], 'references': ''}

    def folders(self) -> list[str]:
        return [f['displayName'] for f in self._request('GET', '/me/mailFolders').get('value', [])]

    def recent(self, folder: str = 'INBOX', days: int = 7, limit: int = 50, unseen_only: bool = False):
        since = (dt.datetime.utcnow() - dt.timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')
        flt = f'receivedDateTime ge {since}' + (' and isRead eq false' if unseen_only else '')
        data = self._request('GET', '/me/mailFolders/inbox/messages' if folder.upper() == 'INBOX'
                             else f'/me/mailFolders/{folder}/messages', params={'$top': limit, '$filter': flt})
        return [self._parse(m, folder) for m in data.get('value', [])]

    def search(self, query: str, folder: str = 'INBOX', limit: int = 30):
        data = self._request('GET', '/me/messages', params={'$search': f'"{query}"', '$top': limit})
        return [self._parse(m, folder) for m in data.get('value', [])]

    def message(self, uid: str, folder: str = 'INBOX') -> dict:
        return self._parse(self._request('GET', f'/me/messages/{uid}'), folder)

    def idle_wait(self, folder='INBOX', seconds=600) -> bool:
        return False

    def move(self, uid: str, source: str, target: str):
        self._request('POST', f'/me/messages/{uid}/move', {'destinationId': target})

    def send(self, message: EmailMessage, recipients: list[str]):
        payload = base64.b64encode(message.as_bytes()).decode()
        from urllib.request import Request, urlopen
        from .oauth import access_token
        token = access_token('microsoft', self.account)
        req = Request(self.BASE + '/me/sendMail', data=payload.encode(), method='POST',
                      headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'text/plain'})
        with urlopen(req, timeout=60):
            pass


def _quote(folder: str) -> str:
    return '"' + str(folder).replace('\\', '\\\\').replace('"', '\\"') + '"'


def _logout(conn):
    try:
        conn.logout()
    except Exception:
        pass


def reply_draft(message: dict, body: str, account: dict, all_recipients: bool = False) -> dict:
    """Draft fields of a reply to ``message`` (quoted original below)."""
    to = addresses(message.get('reply_to') or message.get('from'))
    cc = []
    if all_recipients:
        mine = account.get('address', '').lower()
        cc = [a for a in addresses(message.get('to', '') + ',' + message.get('cc', '')) if a.lower() != mine]
    subject = message.get('subject', '')
    if not re.match(r'(?i)^(re|aw|sv|antw)\s*:', subject):
        subject = 'Re: ' + subject
    quoted = '\n'.join('> ' + line for line in str(message.get('body', '')).splitlines()[:200])
    head = f"On {message.get('date', '')}, {message.get('from', '')} wrote:"
    return {'to': to, 'cc': cc, 'subject': subject, 'body': f'{body.rstrip()}\n\n{head}\n{quoted}\n',
            'in_reply_to': message.get('message_id', ''), 'references': message.get('references', '')}


def forward_draft(message: dict, to, note: str = '') -> dict:
    subject = message.get('subject', '')
    if not re.match(r'(?i)^(fwd?|wg|tr)\s*:', subject):
        subject = 'Fwd: ' + subject
    body = (f"{note.rstrip()}\n\n---------- Forwarded message ----------\nFrom: {message.get('from', '')}\n"
            f"Date: {message.get('date', '')}\nSubject: {message.get('subject', '')}\nTo: {message.get('to', '')}\n\n"
            f"{message.get('body', '')}")
    return {'to': to, 'subject': subject, 'body': body}
