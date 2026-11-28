"""SPM Studio 0.1.0 — the AI assistant is Agent Hub (pinned engine in src/agent_hub), with calendar, to-do
and e-mail. Calendar recurrence, .ics round trip, reminders, the to-do ↔ calendar link (no duplicates), the
first to-do list copied once, the e-mail send rule (no bypass, also with full access and automatic modes),
migration of the classic assistant, no AI options left in the main Settings, no start-up cost, no emoji, and a
privacy scan of the public tree."""
from __future__ import annotations

import ast
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
D = dt.datetime


# ------------------------------------------------------------------ the engine copy
def test_vendored_engine_matches_its_pin():
    sys.path.insert(0, str(ROOT / 'tools'))
    import vendor_agent_hub
    pin = json.loads((SRC / 'spm_studio' / 'assistant' / 'agent_hub.pin.json').read_text(encoding='utf8'))
    assert vendor_agent_hub.tree_sha256(SRC / 'agent_hub') == pin['tree_sha256']
    import agent_hub
    from agent_hub import host
    from spm_studio.assistant import CONTRACT_RANGE
    assert agent_hub.__version__ == pin['version'] and list(host.CONTRACT) == pin['contract']
    assert host.compatible(*CONTRACT_RANGE)


def test_engine_never_imports_spm_studio():
    for path in (SRC / 'agent_hub').rglob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf8'))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or '']
                assert not any(n.startswith('spm_studio') for n in names), path


# ------------------------------------------------------------------ calendar
def test_rrule_expansion():
    from agent_hub.organizer import rrule
    assert rrule.expand('FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4', D(2026, 11, 2, 9)) == \
        [D(2026, 11, 2, 9), D(2026, 11, 4, 9), D(2026, 11, 9, 9), D(2026, 11, 11, 9)]
    assert rrule.expand('FREQ=MONTHLY;BYDAY=-1FR;COUNT=3', D(2026, 11, 27, 16)) == \
        [D(2026, 11, 27, 16), D(2026, 12, 25, 16), D(2027, 1, 29, 16)]
    assert rrule.expand('FREQ=YEARLY;COUNT=2', dt.date(2024, 2, 29)) == [dt.date(2024, 2, 29), dt.date(2028, 2, 29)]
    assert rrule.occurrences('FREQ=DAILY;COUNT=5', D(2026, 12, 1, 8), exdates=[D(2026, 12, 3, 8)]) == \
        [D(2026, 12, 1, 8), D(2026, 12, 2, 8), D(2026, 12, 4, 8), D(2026, 12, 5, 8)]


def test_ics_import_export_round_trip(tmp_path):
    from agent_hub.organizer.links import Organizer
    a = Organizer(tmp_path / 'a')
    ev = a.create_event({'title': 'Seminar; room 2, building A', 'start': '2026-11-03T09:00:00',
                         'end': '2026-11-03T10:30:00', 'tz': 'Europe/Zurich', 'rrule': 'FREQ=WEEKLY;COUNT=6',
                         'exdates': ['2026-11-10T09:00:00'], 'location': 'Building A',
                         'description': 'Line one\nLine two', 'reminders': [10, 1440], 'color': '#8E24AA'})
    a.calendar.update_occurrence(ev['uid'], '2026-11-17T09:00:00', start='2026-11-17T13:00:00',
                                 end='2026-11-17T14:00:00', title='Seminar (afternoon)')
    a.create_event({'title': 'Holiday', 'start': '2026-12-25', 'all_day': True})
    text = a.calendar.export_ics()
    b = Organizer(tmp_path / 'b')
    b.calendar.import_ics(text)
    keys = ('title', 'start', 'end', 'all_day', 'tz', 'rrule', 'exdates', 'location', 'description', 'reminders',
            'overrides', 'color')
    for event in a.calendar.events():
        other = b.calendar.get(event['uid'])
        assert other is not None and {k: event[k] for k in keys} == {k: other[k] for k in keys}


def test_reminder_scheduling(tmp_path):
    from agent_hub.organizer import reminders
    from agent_hub.organizer.links import Organizer
    org = Organizer(tmp_path)
    org.create_event({'title': 'Talk', 'start': '2026-12-01T14:00:00', 'reminders': [10, 60]})
    org.add_task({'title': 'Send figures', 'due': '2026-12-01T16:30'})
    due = reminders.due_between(org, D(2026, 12, 1), D(2026, 12, 2))
    assert [(r['title'], r['at']) for r in due] == [('Talk', D(2026, 12, 1, 13)), ('Talk', D(2026, 12, 1, 13, 50)),
                                                    ('Send figures', D(2026, 12, 1, 16, 30))]
    log = reminders.ReminderLog(tmp_path)
    log.set_last_run(D(2026, 12, 1, 12))
    fired = reminders.pending(org, log, D(2026, 12, 1, 13, 55))
    log.mark(fired, D(2026, 12, 1, 13, 55))
    assert len(fired) == 2 and reminders.pending(org, log, D(2026, 12, 1, 13, 56)) == []
    summary = reminders.start_summary(org, reminders.ReminderLog(tmp_path), D(2026, 12, 2, 8))
    assert [m['title'] for m in summary['missed']] == ['Send figures']


# ------------------------------------------------------------------ to-do
def test_todo_calendar_link_both_ways_without_duplicates(tmp_path):
    from agent_hub.organizer.links import Organizer
    org = Organizer(tmp_path)
    t = org.add_task({'title': 'Prepare slides', 'due': '2026-12-03'})
    uid = t['links']['event']
    org.update_task(t['id'], due='2026-12-04T10:00')
    assert org.calendar.get(uid)['start'] == '2026-12-04T10:00:00'
    org.move_event(uid, '2026-12-05T11:00:00')
    assert org.todo.get(t['id'])['due'] == '2026-12-05T11:00'
    org.set_event_done(uid, True)
    assert org.todo.get(t['id'])['done']
    for _ in range(3):
        org.sync_task(t['id'])
    org.add_task({'title': 'Prepare slides', 'due': '2026-12-05'})            # same title: another task
    assert len([e for e in org.calendar.events() if e['links'].get('todo') == t['id']]) == 1
    meeting = org.create_event({'title': 'Group meeting', 'start': '2026-12-07T10:00:00'})
    first, made = org.ensure_event_task(meeting['uid'], 'prep', 'Prepare slides for group meeting')
    again, made_again = org.ensure_event_task(meeting['uid'], 'prep', 'Slides for the meeting (reworded)')
    assert made and not made_again and first['id'] == again['id']


def test_first_todo_list_copied_once_and_never_modified(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    (tmp_path / 'home').mkdir()
    from spm_studio.documents import todo
    old = todo.file()
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text(json.dumps({'schema_version': 1, 'notes': 'kept notes', 'tasks': [
        {'id': 't0aaaaa', 'text': 'Fit the CPD', 'details': 'scan 12', 'done': False, 'category': 'Analysis'},
        {'id': 't0bbbbb', 'text': 'Write intro', 'details': '', 'done': True, 'category': 'Writing'}]}),
        encoding='utf8')
    before = old.read_bytes()
    from agent_hub import host, organizer
    from spm_studio.assistant.host import SPMHost
    host.set_host(SPMHost())
    organizer.reset()
    org = organizer.shared()
    assert {t['title'] for t in org.todo.tasks()} == {'Fit the CPD', 'Write intro'}
    assert org.todo.notes() == 'kept notes' and old.read_bytes() == before
    organizer.reset()
    assert len(organizer.shared().todo.tasks()) == 2                              # once only
    from spm_studio.assistant.todo_bridge import ai_action
    assert 'Fit the CPD' in ai_action({'app': 'todo', 'action': 'read'})          # the old requests still work
    ai_action({'app': 'todo', 'action': 'update_task', 'item': 't0aaaaa', 'done': True})
    assert organizer.shared().todo.find('t0aaaaa')['done'] and old.read_bytes() == before


# ------------------------------------------------------------------ e-mail: the send rule
@pytest.mark.parametrize('conf', [{'full_access': True}, {'full_access': True, 'auto_sort': 'auto',
                                                          'when_busy': 'auto', 'routing_profile': 'performance'},
                                  {'always_rules': [{'tool': 'mail.send'}, {'tool': 'bash', 'prefix': 'sendmail'}]}])
def test_email_send_approval_cannot_be_bypassed(tmp_path, conf):
    from agent_hub import policy
    from agent_hub.organizer import tools
    from agent_hub.organizer.links import Organizer
    from agent_hub.organizer.mail import ApprovalError, Ticket
    org = Organizer(tmp_path)
    org.mail.add_account({'preset': 'custom', 'address': 'me@example.org',
                          'imap': {'host': 'imap.example.org', 'port': 993, 'security': 'ssl'},
                          'smtp': {'host': 'smtp.example.org', 'port': 587, 'security': 'starttls'}})
    sent = []
    org.mail.outbox.transport = lambda store, item: sent.append(item) or 'sent'
    result = tools.dispatch({'tool': 'mail.send', 'to': 'hr@example.org', 'subject': 'Days', 'body': '9'}, org, conf,
                            approved=True)
    assert result['pending'] == 'outbox' and sent == []
    item = org.mail.outbox.get(result['outbox_id'])
    with pytest.raises(ApprovalError):
        org.mail.outbox.execute(Ticket(item['id'], item['digest'], 'x', 9e12, '0' * 64))
    with pytest.raises(ApprovalError):
        org.mail.outbox.approve(item['id'], 'not-what-was-shown')
    assert sent == []
    for command in ('sendmail hr@example.org < days.txt', 'git push', 'curl -X POST https://x.org -d d=9'):
        assert policy.decide('Bash', {'command': command}, conf, []) == 'ask'
        assert policy.rule_for('Bash', {'command': command}) is None
    ticket = org.mail.outbox.approve(item['id'], item['digest'])                 # the user's click on Send
    org.mail.outbox.execute(ticket)
    assert len(sent) == 1


# ------------------------------------------------------------------ settings and migration
def test_classic_assistant_migration_copies_and_never_modifies(tmp_path, monkeypatch, qapp_session=None):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    (tmp_path / 'home').mkdir()
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from spm_studio.ai import config as aiconf
    aiconf.save({**aiconf.load(), 'backend': 'claude-code', 'configured': True})
    aiconf.save_history('Default', [{'role': 'user', 'content': 'How do I fit a lattice?'},
                                    {'role': 'assistant', 'content': 'Use the lattice tool.'}])
    old_files = {p: p.read_bytes() for p in aiconf.base_dir().rglob('*') if p.is_file()}
    from PySide6.QtCore import QSettings
    main = QSettings(str(tmp_path / 'main.ini'), QSettings.Format.IniFormat)
    main.setValue('ai_dock_floating', True)
    from agent_hub import host
    from agent_hub.core import HubCore
    from spm_studio.assistant import migrate
    from spm_studio.assistant.host import SPMHost
    spm = host.set_host(SPMHost())
    core = HubCore()
    result = migrate.run(core, spm, main)
    assert result['chats'] == 1 and result['default_backend'] == 'claude-code' and result['detached'] is True
    titles = [c['title'] for c in core.store.chats()]
    assert any('classic panel' in t for t in titles) and core.conf['default_backend'] == 'claude-code'
    assert migrate.run(core, spm, main) == {}                                      # once
    assert {p: p.read_bytes() for p in aiconf.base_dir().rglob('*') if p.is_file()} == old_files
    core.shutdown()


def _all_texts(widget):
    from PySide6.QtWidgets import QAbstractButton, QComboBox, QGroupBox, QLabel, QLineEdit
    out = []
    for w in widget.findChildren(QLabel):
        out.append(w.text())
    for w in widget.findChildren(QAbstractButton):
        out.append(w.text())
    for w in widget.findChildren(QGroupBox):
        out.append(w.title())
    for w in widget.findChildren(QLineEdit):
        out.append(w.placeholderText())
    for w in widget.findChildren(QComboBox):
        out += [w.itemText(i) for i in range(w.count())]
    return [re.sub('<[^>]+>', ' ', t) for t in out if t]


def test_no_ai_options_left_in_the_main_settings(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    (tmp_path / 'home').mkdir()
    from PySide6.QtWidgets import QApplication, QPushButton
    QApplication.instance() or QApplication([])
    from spm_studio.ui.main_window import MainWindow
    from spm_studio.ui.settings_dialog import PAGES, SettingsDialog
    win = MainWindow()
    assert 'literature' not in [p[0] for p in PAGES]
    dialog = SettingsDialog(win, 'general')
    dialog.build_all()
    texts = []
    for i in range(dialog.stack.count()):
        if dialog._page_keys[i] in ('about',):        # the licence text only *mentions* the assistant
            continue
        texts += _all_texts(dialog.stack.widget(i))
    joined = '\n'.join(texts)
    banned = [r'\bConsensus\b', r'\bZotero\b', r'\bAPI key\b', r'\bPi agent\b', r'\bClaude\b', r'\bCodex\b',
              r'\bJudge\b', r'\bprovider', r'\bmodel\b', r'\bvoice\b', r'\bfull access\b', r'\be-?mail account']
    found = [p for p in banned if re.search(p, joined, re.I)]
    assert not found, found
    lines = [t for t in texts if re.search(r'\bassistant\b', t, re.I) and 'AI assistant: open its settings' not in t]
    assert not [l for l in lines if 'to-do' not in l.lower() and 'assistant can read' not in l], lines
    button = dialog.findChild(QPushButton, 'OpenAssistantSettingsV010')
    assert button is not None and button.text() == 'Open its settings'
    dialog.close()
    win.close()


def test_main_window_starts_without_any_ai_import(tmp_path):
    """No start-up cost: creating the main window imports no AI engine, backend or provider module."""
    code = ('import sys\nfrom PySide6.QtWidgets import QApplication\napp = QApplication([])\n'
            'from spm_studio.ui.main_window import MainWindow\nw = MainWindow()\napp.processEvents()\n'
            "bad = sorted(m for m in sys.modules if m.startswith(('agent_hub.core', 'agent_hub.agents', "
            "'agent_hub.ui.window', 'spm_studio.ai.pi_rpc', 'spm_studio.ai.providers', 'spm_studio.ai.setup_ui', "
            "'spm_studio.ai.judge')))\nprint('BAD', bad, flush=True)\nw.show()\nw.ai_dock.toggle()\n"
            "app.processEvents()\nprint('OPEN', 'agent_hub.core' in sys.modules and w.ai_dock.is_open(), flush=True)\n"
            "w.close()\napp.processEvents()\n")
    env = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'PYTHONPATH': str(SRC), 'HOME': str(tmp_path),
           'XDG_DATA_HOME': str(tmp_path / 'd'), 'XDG_CONFIG_HOME': str(tmp_path / 'c'),
           'XDG_CACHE_HOME': str(tmp_path / 'k'), 'AGENT_HUB_DATA': str(tmp_path / 'hub')}
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, env=env, timeout=240).stdout
    assert 'BAD []' in out, out
    assert 'OPEN True' in out, out


def test_calendar_and_todo_work_without_ai(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    (tmp_path / 'home').mkdir()
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from spm_studio.ui.main_window import MainWindow
    win = MainWindow()
    cal = win.open_calendar()
    cal.org.create_event({'title': 'Beamtime', 'start': '2026-12-02T08:00:00', 'end': '2026-12-02T12:00:00'})
    cal.set_date(dt.date(2026, 12, 2))
    cal.set_view('week')
    assert [o['title'] for o in cal.grid.occ] == ['Beamtime']
    todo = win.open_todo()
    todo.quick.setText('Order liquid helium tomorrow #lab')
    todo.quick_add()
    assert any(t['title'] == 'Order liquid helium' for t in todo.org.todo.tasks())
    assert 'agent_hub.core' not in sys.modules or win.ai_dock.core is None
    cal.close()
    todo.close()
    win.close()


# ------------------------------------------------------------------ no emoji, privacy
def test_no_emoji_or_font_symbols_in_the_assistant():
    banned = re.compile('[\U0001F000-\U0001FFFF☀-➿⬀-⯿■-◿＋⌘⏩-⏺]')
    offenders = []
    for folder in (SRC / 'agent_hub', SRC / 'spm_studio' / 'assistant'):
        for path in folder.rglob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and banned.search(node.value):
                    offenders.append(f'{path.relative_to(SRC)}:{node.lineno}')
    assert not offenders, offenders
    from agent_hub.ui.svg_icons import ICONS
    assert 'M13 3.5 5.5 13.5' not in ICONS['full']                                 # octopus, not lightning
    from spm_studio.assistant.host import SPMHost
    assert SPMHost().display_text('*' + chr(0x270E) + ' Editor: insert*') == '*Editor: insert*'


# The public client knows only the *public* verification key (update_config.json). Nothing of the private
# extension, its service, its admin console or its signing key may be here. Names are kept as hashes (first 16
# hex digits of SHA-256 of a word or a pair of words) so that this test does not contain them either.
PRIVATE_HASHES = {'0e2365b33be30d6d', '1c340d0edcc0d4f7', '21bf1cbf6d6cb895', '29ea2419bd2990dc', '74cf55f11db5d67d', '9b6d532ca9ab1d13', 'ab225843fda21ca5', 'c9d78a1e9c9656fd', 'd18c533d87b4ea1e', 'd1c128c18e18b5c8', 'fb45631099bb6147'}


def _private_names(text: str) -> list[str]:
    import hashlib
    words = re.findall(r'[A-Za-z_][A-Za-z0-9_-]*', text)
    return [w for w in words + [a + ' ' + b for a, b in zip(words, words[1:])]
            if hashlib.sha256(w.encode()).hexdigest()[:16] in PRIVATE_HASHES]


TOKENS = re.compile(r'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-(?:ant-)?[A-Za-z0-9]{32,}|'
                    r'AIza[0-9A-Za-z_-]{30,}|xox[abprs]-[0-9A-Za-z-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|'
                    r'ya29\.[0-9A-Za-z_-]{20,}')


def _tracked_files():
    try:
        out = subprocess.run(['git', '-C', str(ROOT), 'ls-files'], capture_output=True, text=True, check=True).stdout
        return [ROOT / f for f in out.splitlines() if f]
    except (OSError, subprocess.CalledProcessError):
        return [p for p in ROOT.rglob('*') if p.is_file() and '.git' not in p.parts]


def test_public_tree_privacy_scan():
    """No private extension, no signing key, no token, no personal path of this computer in the public tree."""
    home = str(Path.home())
    problems = []
    for path in _tracked_files():
        if not path.is_file() or path.suffix in ('.png', '.otf', '.ttf', '.sxm', '.gwy', '.ico', '.zip', '.npz',
                                                  '.jpg', '.pdf', '.icns'):
            continue
        if path.suffix in ('.b64', '.pem', '.key') or path.name in ('manifest.sig',):
            problems.append(f'{path.relative_to(ROOT)}: key-like file')
            continue
        try:
            text = path.read_text(encoding='utf8')
        except (UnicodeDecodeError, OSError):
            continue
        for name in _private_names(text):
            problems.append(f'{path.relative_to(ROOT)}: {name}')
        if TOKENS.search(text):
            problems.append(f'{path.relative_to(ROOT)}: token-like string')
        if len(home) > 6 and home not in ('/root',) and home in text:
            problems.append(f'{path.relative_to(ROOT)}: a path of this computer')
    assert not problems, problems


# ------------------------------------------------------------------ older extensions with their own assistant
def test_an_older_extension_cannot_replace_the_built_in_assistant(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    (tmp_path / 'home').mkdir()
    from PySide6.QtGui import QKeySequence, QShortcut
    from PySide6.QtWidgets import QApplication, QLabel
    QApplication.instance() or QApplication([])
    from spm_studio.ui.main_window import MainWindow
    win = MainWindow()
    hijacked = []
    try:                                               # what an older extension did at activation
        win.ai_toolbar_button.clicked.disconnect()
    except (RuntimeError, TypeError):
        pass
    win.ai_toolbar_button.clicked.connect(lambda *_: hijacked.append('button'))
    foreign = QShortcut(QKeySequence('Ctrl+Alt+A'), win)
    win.extension_api.settings_pages['ext:old-ext:agent-hub'] = ('old-ext', 'Old assistant', lambda p: QLabel('x'))
    win._keep_builtin_assistant()
    assert not foreign.isEnabled() and win._assistant_shortcut.isEnabled()
    win.ai_toolbar_button.click()
    assert hijacked == [] and win.ai_dock.is_open() in (True, False)
    from spm_studio.ui.settings_dialog import SettingsDialog
    dialog = SettingsDialog(win, 'general')
    assert 'ext:old-ext:agent-hub' not in dialog._page_keys
    dialog.close()
    win.ai_dock.close_panel()
    win.close()


def test_extension_copy_of_the_engine_never_shadows_the_built_in_one(tmp_path, monkeypatch):
    shadow = tmp_path / 'ext' / 'agent_hub'
    shadow.mkdir(parents=True)
    (shadow / '__init__.py').write_text("__version__ = '0.0.0-shadow'\n", encoding='utf8')
    for name in [m for m in sys.modules if m == 'agent_hub' or m.startswith('agent_hub.')]:
        monkeypatch.delitem(sys.modules, name)
    from spm_studio.beta import extensions
    monkeypatch.setattr(extensions, 'installed', lambda: {})
    extensions.load_enabled(None, False)                # imports the built-in engine first
    monkeypatch.syspath_prepend(str(tmp_path / 'ext'))
    import agent_hub
    assert agent_hub.__version__ != '0.0.0-shadow' and Path(agent_hub.__file__).parent == SRC / 'agent_hub'
