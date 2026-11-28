"""Administrative e-mails (Qt-free): an e-mail asks the user to fill something in (home-office days, a form,
a timesheet, an attestation …). The workflow:

1. :func:`detect` recognises the request (English, French, German) and its deadline;
   :func:`start` creates a to-do with that deadline, linked to the e-mail (once per message).
2. :func:`gather` collects what it can: counted calendar entries / to-dos for the period (e.g. "Home office"
   days in November), and the user's earlier answers to the same question (``admin_answers.json``).
3. Only the missing values are asked, in a compact form card (``ui/organizer/cards.py``).
4. :func:`fill_pdf` fills the PDF's form fields when it has some (pypdf), otherwise it adds an overlay page
   listing the values; :func:`reply_text` prepares the answer.
5. The filled PDF and the reply are shown side by side; the reply is a *proposal* in the outbox — it leaves
   only after the user presses Send (``mail.Outbox``).
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .base import atomic_write, read_json
from .todo import parse_quick

KEYWORDS = {
    'request': [r'\bfill (?:in|out)\b', r'\bcomplete (?:the|this|your) (?:form|survey|sheet)\b', r'\bplease (?:report|declare|indicate|send us|provide|confirm)\b',
                r'\bremplir\b', r'\bcompl[ée]ter\b', r'\bmerci de (?:nous )?(?:indiquer|renseigner|d[ée]clarer|transmettre|retourner)\b',
                r'\bausf[üu]llen\b', r'\bbitte (?:melden|angeben|tragen|teilen|senden|best[äa]tigen)\b', r'\bto be returned\b'],
    'topic': [r'\bhome[- ]?office\b', r'\bt[ée]l[ée]travail\b', r'\bhomeoffice\b', r'\bremote work(?:ing)?\b',
              r'\btimesheet\b', r'\bfeuille de temps\b', r'\bstundenzettel\b', r'\barbeitszeit\b', r'\bform\b',
              r'\bformulaire\b', r'\bformular\b', r'\battestation\b', r'\bdeclaration\b', r'\bd[ée]claration\b',
              r'\bexpense report\b', r'\bnote de frais\b', r'\bspesen\b', r'\bvacation days?\b', r'\bcong[ée]s\b',
              r'\burlaub\b', r'\bhours?\b', r'\bdays?\b', r'\bjours\b', r'\btage\b'],
    'deadline': [r'\b(?:by|before|until|no later than|deadline)\b', r'\b(?:avant le|d\'ici le|au plus tard|jusqu\'au)\b',
                 r'\b(?:bis(?: zum)?|sp[äa]testens)\b'],
}
QUANTITIES = [
    {'key': 'home_office_days', 'label': 'Home-office days', 'unit': 'days',
     'patterns': [r'home[- ]?office', r't[ée]l[ée]travail', r'homeoffice', r'remote work'],
     'calendar': [r'\bhome[- ]?office\b', r'\bt[ée]l[ée]travail\b', r'\bhomeoffice\b', r'\bremote\b', r'\bHO\b',
                  r'\bWFH\b', r'\bwork from home\b']},
    {'key': 'vacation_days', 'label': 'Vacation days', 'unit': 'days',
     'patterns': [r'vacation', r'holiday', r'cong[ée]s', r'urlaub', r'leave days'],
     'calendar': [r'\bvacation\b', r'\bholiday\b', r'\bcong[ée]s?\b', r'\burlaub\b', r'\bleave\b']},
    {'key': 'hours_worked', 'label': 'Hours worked', 'unit': 'hours',
     'patterns': [r'hours worked', r'working hours', r'timesheet', r'heures', r'arbeitsstunden', r'stunden'],
     'calendar': []},
]
MONTH_NAMES = {**{m: i for i, m in enumerate(['january', 'february', 'march', 'april', 'may', 'june', 'july',
                                               'august', 'september', 'october', 'november', 'december'], 1)},
               **{m: i for i, m in enumerate(['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet',
                                               'août', 'septembre', 'octobre', 'novembre', 'décembre'], 1)},
               **{m: i for i, m in enumerate(['januar', 'februar', 'märz', 'april', 'mai', 'juni', 'juli',
                                               'august', 'september', 'oktober', 'november', 'dezember'], 1)}}


def _score(text: str, group: str) -> int:
    return sum(1 for p in KEYWORDS[group] if re.search(p, text, re.I))


def detect(message: dict, today: dt.date | None = None) -> dict | None:
    """``{'kind', 'deadline', 'quantities', 'period', 'pdf_attachments', 'reason'}`` or None."""
    today = today or dt.date.today()
    text = f"{message.get('subject', '')}\n{message.get('body', '')}"
    req, topic = _score(text, 'request'), _score(text, 'topic')
    pdfs = [a for a in message.get('attachments') or [] if str(a.get('name', '')).lower().endswith('.pdf')]
    form_pdf = any(re.search(r'form|formulaire|formular|attestation|declaration|timesheet', a['name'], re.I)
                   for a in pdfs)
    if not (req and (topic or pdfs)) and not (form_pdf and topic):
        return None
    quantities = [q for q in QUANTITIES if any(re.search(p, text, re.I) for p in q['patterns'])]
    return {'kind': 'form' if pdfs else 'reply', 'deadline': find_deadline(text, today),
            'quantities': [q['key'] for q in quantities], 'period': find_period(text, today),
            'pdf_attachments': pdfs, 'reason': f'{req} request phrase(s), {topic} topic word(s)'}


def find_deadline(text: str, today: dt.date) -> str:
    for p in KEYWORDS['deadline']:
        for m in re.finditer(p, text, re.I):
            tail = text[m.end():m.end() + 40]
            tail = re.split(r'[\n;]', tail)[0]
            found = parse_quick(_normalize_dates(tail), today)['due']
            if found:
                return found[:10]
    m = re.search(r'\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b', text)
    if m:
        try:
            return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            pass
    return ''


def _normalize_dates(text: str) -> str:
    """'5 décembre' / '5. Dezember' / 'le 5 décembre' → '5 dec' (what the quick-add parser reads)."""
    names = '|'.join(sorted(MONTH_NAMES, key=len, reverse=True))
    return re.sub(r'\b(\d{1,2})\s*(?:er|st|nd|rd|th|\.)?\s+(' + names + r')\b',
                  lambda m: f"{m.group(1)} {_en(m.group(2))}", text, flags=re.I)


def _en(month: str) -> str:
    return ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'][
        MONTH_NAMES[month.lower()] - 1]


def find_period(text: str, today: dt.date) -> dict:
    """The month (or year) the request is about; default: the previous month."""
    names = '|'.join(sorted(MONTH_NAMES, key=len, reverse=True))
    m = re.search(r'\b(?:for|of|in|pour|de|du mois de|für|im)?\s*(' + names + r')\s*(\d{4})?\b', text, re.I)
    if m:
        month = MONTH_NAMES[m.group(1).lower()]
        year = int(m.group(2)) if m.group(2) else (today.year if month <= today.month else today.year - 1)
    else:
        first = today.replace(day=1) - dt.timedelta(days=1)
        month, year = first.month, first.year
    start = dt.date(year, month, 1)
    end = (start + dt.timedelta(days=32)).replace(day=1)
    return {'start': start.isoformat(), 'end': end.isoformat(), 'label': start.strftime('%B %Y')}


# ------------------------------------------------------------------------------------------ steps
def start(organizer, message: dict, found: dict) -> tuple[dict, bool]:
    """The to-do for this e-mail (created once, linked by message id)."""
    key = message.get('message_id') or f"{message.get('account')}|{message.get('uid')}"
    for t in organizer.todo.tasks():
        if (t.get('links') or {}).get('email') == key:
            return t, False
    title = 'Answer: ' + (message.get('subject') or 'administrative e-mail')[:120]
    task = organizer.add_task({'title': title, 'due': found.get('deadline', ''), 'priority': 2, 'tags': ['admin'],
                               'notes': f"From {message.get('from', '')}\n\n{message.get('snippet', '')}",
                               'links': {'email': key}}, created_by='email')
    return task, True


def _answers_path(root: Path) -> Path:
    return Path(root) / 'admin_answers.json'


def remember_answers(root: Path, values: dict):
    data = read_json(_answers_path(root), {})
    for k, v in values.items():
        if str(v).strip():
            data[k] = {'value': v, 'at': dt.datetime.now().isoformat(timespec='seconds')}
    atomic_write(_answers_path(root), data)


def gather(organizer, found: dict, fields: list[dict] | None = None) -> list[dict]:
    """Fields to show in the form card: ``{'key', 'label', 'value', 'source', 'missing'}``."""
    period = found.get('period') or {}
    p0 = dt.date.fromisoformat(period['start']) if period.get('start') else None
    p1 = dt.date.fromisoformat(period['end']) if period.get('end') else None
    earlier = read_json(_answers_path(organizer.root), {})
    out = []
    for q in QUANTITIES:
        if q['key'] not in found.get('quantities', []):
            continue
        value, source = '', ''
        if q['calendar'] and p0 and p1:
            days = set()
            for o in organizer.calendar.occurrences(p0, p1, visible_only=False):
                if any(re.search(p, o['title'], re.I) for p in q['calendar']):
                    s = o['start'] if not isinstance(o['start'], dt.datetime) else o['start'].date()
                    e = o['end'] if not isinstance(o['end'], dt.datetime) else o['end'].date()
                    day = s
                    while day < max(e, s + dt.timedelta(days=1)) and day < p1:
                        if day >= p0 and day.weekday() < 5:
                            days.add(day)
                        day += dt.timedelta(days=1)
            for t in organizer.todo.tasks():
                if t.get('done') and any(re.search(p, t['title'], re.I) for p in q['calendar']) and t.get('done_at'):
                    d = dt.date.fromisoformat(t['done_at'][:10])
                    if p0 <= d < p1:
                        days.add(d)
            if days:
                value = str(len(days))
                source = f"counted in your calendar for {period.get('label', '')}: " + \
                    ', '.join(d.strftime('%d') for d in sorted(days))
        if not value and q['key'] in earlier:
            value, source = str(earlier[q['key']]['value']), f"your earlier answer ({earlier[q['key']]['at'][:10]})"
        out.append({'key': q['key'], 'label': f"{q['label']} ({period.get('label', '')})" if period else q['label'],
                    'value': value, 'source': source, 'missing': not value})
    for f in fields or []:
        key = f['name']
        value = str(f.get('value') or '')
        source = 'already in the form' if value else ''
        if not value and key in earlier:
            value, source = str(earlier[key]['value']), f"your earlier answer ({earlier[key]['at'][:10]})"
        if not value:
            guess = _guess_field(organizer, key, found)
            if guess:
                value, source = guess
        out.append({'key': key, 'label': f.get('label') or key, 'value': value, 'source': source,
                    'missing': not value, 'pdf_field': True, 'type': f.get('type', 'text'),
                    'options': f.get('options', [])})
    return out


def _guess_field(organizer, name: str, found: dict):
    low = name.lower()
    period = found.get('period') or {}
    if re.search(r'date|datum', low) and not re.search(r'birth|naissance|geburt', low):
        return dt.date.today().strftime('%d.%m.%Y'), 'today'
    if re.search(r'month|mois|monat|period|p[ée]riode|zeitraum', low) and period:
        return period['label'], 'the period named in the e-mail'
    for q in QUANTITIES:
        if any(re.search(p, low, re.I) for p in q['patterns']):
            gathered = gather(organizer, dict(found, quantities=[q['key']]))
            if gathered and gathered[0]['value']:
                return gathered[0]['value'], gathered[0]['source']
    return None


# ------------------------------------------------------------------------------------------ PDF
def pdf_fields(path: Path) -> list[dict]:
    """Form fields of a PDF (empty list when it has none or pypdf is missing)."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return []
    try:
        reader = PdfReader(str(path))
        fields = reader.get_fields() or {}
    except Exception:
        return []
    out = []
    for name, f in fields.items():
        ftype = str(f.get('/FT', ''))
        if ftype not in ('/Tx', '/Btn', '/Ch'):
            continue
        options = [str(o) for o in (f.get('/_States_', []) or f.get('/Opt', []) or [])]
        out.append({'name': name, 'label': str(f.get('/TU') or name), 'value': str(f.get('/V') or '').lstrip('/'),
                    'type': {'/Tx': 'text', '/Btn': 'check', '/Ch': 'choice'}[ftype], 'options': options})
    return out


def fill_pdf(source: Path, target: Path, values: dict, overlay_writer=None) -> dict:
    """Fill form fields (``values`` by field name); without form fields, append an overlay page with the values
    (``overlay_writer(values) -> pdf bytes``, provided by the Qt layer). Returns {'method', 'filled'}."""
    from pypdf import PdfReader, PdfWriter
    reader = PdfReader(str(source))
    writer = PdfWriter()
    writer.append(reader)
    fields = reader.get_fields() or {}
    filled = 0
    if fields:
        known = {k: v for k, v in values.items() if k in fields}
        for page in writer.pages:
            try:
                writer.update_page_form_field_values(page, known, auto_regenerate=False)
            except Exception:
                continue
        writer.set_need_appearances_writer(True)
        filled = len(known)
        method = 'form fields'
    else:
        method = 'overlay page'
        if overlay_writer is not None:
            import io
            extra = PdfReader(io.BytesIO(overlay_writer(values)))
            for page in extra.pages:
                writer.add_page(page)
            filled = len(values)
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    with open(target, 'wb') as f:
        writer.write(f)
    return {'method': method, 'filled': filled}


def reply_text(message: dict, values: list[dict], attached: bool, language: str = '') -> str:
    """A short, polite answer with the values (the assistant may rewrite it; the user edits before sending)."""
    text = f"{message.get('subject', '')} {message.get('body', '')}".lower()
    lang = language or ('fr' if re.search(r'\b(bonjour|merci|veuillez|cordialement)\b', text) else
                        'de' if re.search(r'\b(hallo|danke|bitte|grüße|gruesse|freundlich)\b', text) else 'en')
    lines = [f"- {v['label']}: {v['value']}" for v in values if str(v.get('value', '')).strip()]
    if lang == 'fr':
        head = 'Bonjour,\n\nVoici les informations demandées :'
        tail = ('Vous trouverez le formulaire rempli en pièce jointe.\n\n' if attached else '') + 'Cordialement'
    elif lang == 'de':
        head = 'Guten Tag,\n\nhier die gewünschten Angaben:'
        tail = ('Das ausgefüllte Formular finden Sie im Anhang.\n\n' if attached else '') + 'Freundliche Grüße'
    else:
        head = 'Hello,\n\nHere is the information you asked for:'
        tail = ('Please find the completed form attached.\n\n' if attached else '') + 'Best regards'
    return head + '\n' + '\n'.join(lines) + '\n\n' + tail + '\n'
