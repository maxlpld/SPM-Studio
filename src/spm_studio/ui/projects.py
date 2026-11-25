"""Projects, autosave and crash recovery for the main window (v0.0.20).

* **New project…** / **Open project…** (top bar): a project is a folder; its state is saved in
  ``spm-studio-project.json`` inside it (see ``core.project``). Opening a folder that has no project file yet
  makes it a project and lists its scans (what *Dataset…* did before).
* **Several projects at once**: each open project is a tab above the scan list. Switching tabs saves the project
  you leave and restores the other one exactly as it was; nothing is shared between them (scan list, display,
  processing, crops, selections, tool settings).
* **Autosave**: the state of the active project is written every few seconds when it changed (Settings › General
  › Projects and recovery) — in a background thread, so a slow disk never freezes the window. Scans opened without
  a project are kept as an *unsaved session* in the recovery folder.
* **Recovery**: at start, the projects that were open are reopened at the scan, channel and step where you were —
  after a normal close as well as after a crash or an accidental close.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import QFileDialog, QTabBar

from spm_studio.core import project as proj
from spm_studio.shared.dialogs import MessageDialog as QMessageBox


class Slot:
    """One open project (``folder`` None = the unsaved session)."""

    def __init__(self, folder: Path | None, document: dict):
        self.folder = Path(folder) if folder else None
        self.document = document
        self.last_text = ''            # JSON last written (skip identical saves)

    @property
    def name(self) -> str:
        return self.document.get('name') or (proj.default_name(self.folder) if self.folder else 'Unsaved session')

    @property
    def path(self) -> Path:
        return proj.project_file(self.folder) if self.folder else proj.session_file()


class _Writer:
    """Writes project files in one background thread (latest content wins)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._busy = threading.Lock()          # held while a file is being written
        self._jobs: dict[str, tuple[Path, dict]] = {}
        self._event = threading.Event()
        self._errors: list[str] = []
        self._thread = threading.Thread(target=self._run, name='spm-project-writer', daemon=True)
        self._thread.start()

    def submit(self, path: Path, data: dict):
        with self._lock:
            self._jobs[str(path)] = (path, data)
        self._event.set()

    def _run(self):
        while True:
            self._event.wait()
            self._event.clear()
            while True:
                with self._lock:
                    if not self._jobs:
                        break
                    key = next(iter(self._jobs))
                    path, data = self._jobs.pop(key)
                    self._busy.acquire()
                try:
                    proj.write_json_atomic(path, data)
                except Exception as exc:
                    with self._lock:
                        self._errors.append(f'{path}: {exc}')
                finally:
                    self._busy.release()

    def errors(self) -> list[str]:
        with self._lock:
            out, self._errors = self._errors, []
        return out

    def flush(self, timeout: float = 3.0):
        """Write everything now (used when SPM Studio closes)."""
        with self._lock:
            jobs, self._jobs = list(self._jobs.values()), {}
        if self._busy.acquire(timeout=timeout):        # let a write in progress finish first
            try:
                for path, data in jobs:
                    try:
                        proj.write_json_atomic(path, data)
                    except Exception as exc:
                        self._errors.append(f'{path}: {exc}')
            finally:
                self._busy.release()


class ProjectManager(QObject):
    changed = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.w = window
        self.slots: list[Slot] = []
        self.active = -1
        self.generation = 0            # bumps when the active project changes (late crawler results are ignored)
        self._switching = False
        self._writer = _Writer()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.autosave)
        try:
            seconds = int(float(window.settings.value('project/autosave_seconds', 15)))
        except (TypeError, ValueError):
            seconds = 15
        self.set_interval(seconds)
        self.tabs = QTabBar()
        self.tabs.setObjectName('ProjectTabsV0020')
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(False)
        self.tabs.setExpanding(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideMiddle)
        self.tabs.setDocumentMode(True)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabCloseRequested.connect(self.close_project)

    # ------------------------------------------------------------------ settings
    def set_interval(self, seconds: int):
        self.timer.setInterval(max(5, min(300, int(seconds))) * 1000)
        self.timer.start()

    def reopen_enabled(self) -> bool:
        return str(self.w.settings.value('project/reopen_last', True)).lower() in ('true', '1')

    # ------------------------------------------------------------------ state of the window → document
    def _stored(self, path: str, folder) -> str:
        return proj.to_stored_path(path, folder)

    def capture(self, slot: Slot | None = None) -> dict:
        """The state of the window as a project document (nothing is written here)."""
        w = self.w
        slot = slot or self.current()
        folder = slot.folder if slot else None
        doc = dict(slot.document) if slot else proj.new_document()
        try:
            w._remember_scan_view()
        except Exception:
            pass
        rel = lambda p: self._stored(p, folder)
        files = list(dict.fromkeys(w._source_paths))
        views = {}
        listed = set(files)
        for path, view in w._scan_view_states.items():
            if path not in listed:
                continue
            item = {k: v for k, v in view.items() if k not in ('crop_region', 'crop_applied')}
            item['crop_region'] = proj.crop_to_dict(view.get('crop_region'))
            item['crop_applied'] = sorted(view.get('crop_applied') or [])
            views[rel(path)] = item
        active = str(w.scan.path) if w.scan is not None else None
        if active and rel(active) in views:
            viewer = w.viewer
            views[rel(active)]['rois'] = {'roi': viewer.roi.to_dict() if viewer.roi else None,
                                          'extra': [r.to_dict() for r in viewer.extra_rois]}
        styles = {proj.key_text((rel(k[0]),) + tuple(k[1:])): proj.style_to_dict(v)
                  for k, v in w.styles.items() if k[0] in files}
        pipelines = {proj.key_text((rel(k[0]),) + tuple(k[1:])): proj.steps_to_list(v)
                     for k, v in w.pipelines.items() if k[0] in files and v}
        masks = {}
        for key, value in w._session_masks.items():
            if isinstance(key, tuple) and key and key[0] in files:
                masks[proj.key_text((rel(key[0]),) + tuple(key[1:]))] = value
        tool = w.browser.tools.currentItem()
        tool_id = tool.data(Qt.ItemDataRole.UserRole) if tool is not None else None
        try:
            tool_values = w.module_panel.values() if w.module_panel.module is not None else {}
        except Exception:
            tool_values = {}
        current_item = w.browser.files.currentItem()
        current = active or (current_item.data(Qt.ItemDataRole.UserRole) if current_item else None)
        doc.update({
            'format': proj.FORMAT, 'version': proj.VERSION,
            'name': slot.name if slot else doc.get('name', ''),
            'scans': [rel(p) for p in files],
            'removed': sorted(rel(p) for p in w._removed_paths),
            'current': rel(current) if current else None,
            'state': {'views': views, 'styles': styles, 'pipelines': pipelines, 'masks': masks,
                      'profiles': {rel(k): v for k, v in w._scan_profile_keys.items() if k in files},
                      'pending_profiles': sorted(rel(p) for p in w._pending_bulk_profiles if p in files),
                      'tool': tool_id if isinstance(tool_id, str) and not tool_id.startswith('__') else None,
                      'tool_values': _jsonable(tool_values),
                      'right_tab': w.right_tabs.currentIndex(),
                      'left_tab': w.browser.tabs.currentIndex()},
        })
        return doc

    # ------------------------------------------------------------------ document → window
    def apply(self, slot: Slot, *, index_folder: bool = True):
        """Show ``slot`` in the window (the session must already be empty)."""
        w = self.w
        doc = slot.document
        folder = slot.folder
        state = doc.get('state') or {}
        absp = lambda t: proj.from_stored_path(t, folder)
        w._session_folder = folder
        if folder is not None:
            w._dialog_folder = folder
        w._removed_paths = {absp(t) for t in doc.get('removed', [])}
        views = {}
        for text, view in (state.get('views') or {}).items():
            item = dict(view)
            try:
                item['crop_region'] = proj.crop_from_dict(view.get('crop_region'))
            except Exception:
                item['crop_region'] = None
            item['crop_applied'] = set(view.get('crop_applied') or [])
            views[absp(text)] = item
        w._scan_view_states = views
        w.styles = {}
        for text, value in (state.get('styles') or {}).items():
            key = proj.key_from_text(text)
            try:
                w.styles[(absp(key[0]),) + tuple(key[1:])] = proj.style_from_dict(value)
            except Exception:
                pass
        w.pipelines = {}
        for text, value in (state.get('pipelines') or {}).items():
            key = proj.key_from_text(text)
            w.pipelines[(absp(key[0]),) + tuple(key[1:])] = proj.steps_from_list(value)
        w._session_masks = {}
        for text, value in (state.get('masks') or {}).items():
            key = proj.key_from_text(text)
            w._session_masks[(absp(key[0]),) + tuple(key[1:])] = value
        w._scan_profile_keys = {absp(k): v for k, v in (state.get('profiles') or {}).items()}
        w._pending_bulk_profiles = {absp(p) for p in state.get('pending_profiles', [])}
        missing = []
        files = w.browser.files
        blocked = files.blockSignals(True)
        try:
            for text in doc.get('scans', []):
                path = absp(text)
                if Path(path).is_file():
                    w._add_file(path, select=False)
                else:
                    missing.append(path)
        finally:
            files.blockSignals(blocked)
        if missing:
            w._log(f'{len(missing)} scan(s) of “{slot.name}” were not found (moved or deleted): '
                   + ', '.join(Path(p).name for p in missing[:5]) + (' …' if len(missing) > 5 else ''),
                   important=True)
        try:
            w.right_tabs.setCurrentIndex(int(state.get('right_tab', 0)))
            w.browser.tabs.setCurrentIndex(int(state.get('left_tab', 0)))
        except (TypeError, ValueError):
            pass
        tool = state.get('tool')
        if tool:
            w._pending_tool_restore = (tool, state.get('tool_values') or {})
            for i in range(w.browser.tools.count()):
                if w.browser.tools.item(i).data(Qt.ItemDataRole.UserRole) == tool:
                    w.browser.tools.setCurrentRow(i)
                    break
        current = absp(doc['current']) if doc.get('current') else None
        rois = (views.get(current) or {}).get('rois') if current else None
        w._pending_roi_restore = (current, rois) if rois else None
        target = None
        for i in range(files.count()):
            if files.item(i).data(Qt.ItemDataRole.UserRole) == current:
                target = files.item(i)
                break
        if target is None and files.count():
            target = files.item(0)
        if target is not None:
            files.setCurrentItem(target)
            files.scrollToItem(target)
        if folder is not None and index_folder:
            w._open_dataset_folder(folder, keep_removed=True)
        w.browser.update_selection_actions()

    # ------------------------------------------------------------------ slots / tabs
    def current(self) -> Slot | None:
        return self.slots[self.active] if 0 <= self.active < len(self.slots) else None

    def _add_slot(self, slot: Slot) -> int:
        self.slots.append(slot)
        blocked = self.tabs.blockSignals(True)
        try:
            index = self.tabs.addTab(slot.name)
            self.tabs.setTabToolTip(index, str(slot.folder) if slot.folder else
                                    'Scans opened without a project (kept for recovery). '
                                    'New project… saves them in a folder.')
        finally:
            self.tabs.blockSignals(blocked)
        self._update_tabs()
        return len(self.slots) - 1

    def _update_tabs(self):
        self.tabs.setVisible(len(self.slots) > 1 or any(s.folder for s in self.slots))
        for i, slot in enumerate(self.slots):
            self.tabs.setTabText(i, slot.name)
        try:
            self.w.update_project_title()
        except Exception:
            pass
        self.changed.emit()

    def find(self, folder) -> int:
        if folder is None:
            return next((i for i, s in enumerate(self.slots) if s.folder is None), -1)
        try:
            target = Path(folder).resolve()
        except OSError:
            target = Path(folder)
        for i, s in enumerate(self.slots):
            if s.folder is not None:
                try:
                    if s.folder.resolve() == target:
                        return i
                except OSError:
                    pass
        return -1

    def ensure_session(self):
        """There is always one active slot; the first is the unsaved session."""
        if self.current() is None:
            index = self.find(None)
            if index < 0:
                index = self._add_slot(Slot(None, proj.new_document('Unsaved session')))
            self.active = index
            blocked = self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(index)
            self.tabs.blockSignals(blocked)
        return self.current()

    def _busy(self) -> bool:
        if getattr(self.w, 'job', None) is not None:
            QMessageBox.information(self.w, 'Analysis running',
                                    'Wait until the running analysis has finished (or cancel it) before changing '
                                    'project.')
            return True
        return False

    def activate(self, index: int, *, index_folder: bool = True):
        if index == self.active or not (0 <= index < len(self.slots)):
            return
        if self._switching:
            return
        if self.current() is not None and self._busy():
            blocked = self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(self.active)
            self.tabs.blockSignals(blocked)
            return
        self._switching = True
        try:
            old = self.current()
            if old is not None:
                old.document = self.capture(old)
                self._save(old, force=True)
            self.generation += 1
            self.w._reset_session()
            self.active = index
            blocked = self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(index)
            self.tabs.blockSignals(blocked)
            self.apply(self.slots[index], index_folder=index_folder)
            self._remember_open()
        finally:
            self._switching = False
        self._update_tabs()

    def _tab_changed(self, index):
        self.activate(index)

    def close_project(self, index: int):
        if not (0 <= index < len(self.slots)):
            return
        slot = self.slots[index]
        if index == self.active and self._busy():
            return
        if index == self.active:
            slot.document = self.capture(slot)
        self._save(slot, force=True)
        if index == self.active:
            # Show a neighbour (or an empty unsaved session).
            others = [i for i in range(len(self.slots)) if i != index]
            if others:
                self.activate(min(others, key=lambda i: abs(i - index)))
            else:
                self.generation += 1
                self.w._reset_session()
                self.active = -1
        self.slots.pop(index)
        blocked = self.tabs.blockSignals(True)
        self.tabs.removeTab(index)
        self.tabs.blockSignals(blocked)
        if self.active > index:
            self.active -= 1
        if slot.folder is None:
            try:
                proj.session_file().unlink(missing_ok=True)
            except OSError:
                pass
        self.ensure_session()
        blocked = self.tabs.blockSignals(True)
        self.tabs.setCurrentIndex(self.active)
        self.tabs.blockSignals(blocked)
        self._remember_open()
        self._update_tabs()
        self.w._log(f'Closed project {slot.name} (saved)' if slot.folder else 'Closed the unsaved session')

    # ------------------------------------------------------------------ user commands
    def new_project(self):
        start = str(self.w._dialog_folder)
        folder = QFileDialog.getExistingDirectory(self.w, 'New project — choose or create its folder', start)
        if not folder:
            return
        folder = Path(folder)
        if proj.is_project_folder(folder):
            answer = QMessageBox.question(
                self.w, 'New project',
                f'“{folder.name}” already contains an SPM Studio project.\n\nOpen it as it is? (No starts a new '
                'project in this folder; the previous state is kept as a .bak copy.)')
            if answer == QMessageBox.StandardButton.Yes:
                self.open_folder(folder)
                return
            try:
                proj.save_project(folder, proj.new_document(proj.default_name(folder), folder))
            except OSError as exc:
                QMessageBox.warning(self.w, 'New project', f'The project file could not be written:\n{exc}')
                return
        # The scans of the unsaved session move into the new project (they are what the user is working on).
        session = self.current() if self.current() is not None and self.current().folder is None else None
        carry = session is not None and bool(self.w._source_paths) and QMessageBox.question(
            self.w, 'New project', f'Put the {len(self.w._source_paths)} scan(s) listed now into “{folder.name}”?'
            '\n\n(The files themselves are not moved or copied.)') == QMessageBox.StandardButton.Yes
        if carry:
            doc = self.capture(session)
            doc['name'] = proj.default_name(folder)
            doc['id'] = proj.new_document()['id']
            # re-express the paths relative to the new folder
            slot = Slot(folder, _rebase(doc, None, folder))
            try:
                proj.session_file().unlink(missing_ok=True)
            except OSError:
                pass
            self.generation += 1
            self.w._reset_session()
            old_index = self.active
            self.slots.pop(old_index)                 # the unsaved session became the project
            blocked = self.tabs.blockSignals(True)
            self.tabs.removeTab(old_index)
            self.tabs.blockSignals(blocked)
            self.active = -1
            index = self._add_slot(slot)
            self.active = index
            self.generation += 1
            blocked = self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(index)
            self.tabs.blockSignals(blocked)
            self.apply(slot)
            self._save(slot, force=True)
            self._remember_open()
            self._update_tabs()
        else:
            self.open_folder(folder, create=True, save_now=True)
        proj.add_recent(folder)
        self.w._log(f'New project {folder.name}: its state is saved in {proj.project_file(folder)}', important=True)

    def open_project(self):
        folder = QFileDialog.getExistingDirectory(self.w, 'Open project — choose the project (or scans) folder',
                                                  str(self.w._dialog_folder))
        if folder:
            self.open_folder(Path(folder))

    def open_folder(self, folder, *, create: bool = True, index: bool = True, save_now: bool = False):
        """Open ``folder`` as a project (a tab); a folder without project file becomes one."""
        folder = Path(folder)
        existing = self.find(folder)
        if existing >= 0:
            self.activate(existing)
            return self.slots[existing]
        try:
            document = proj.load_project(folder)
        except ValueError as exc:
            QMessageBox.warning(self.w, 'Open project', str(exc))
            return None
        fresh = document is None
        if fresh:
            if not create:
                return None
            document = proj.new_document(proj.default_name(folder), folder)
        slot = Slot(folder, document)
        if self.current() is not None and self._busy():
            return None
        session = self.current()
        if session is not None and session.folder is None and not self.w._source_paths and \
                not (session.document.get('scans')):
            # an empty unsaved session is simply replaced
            self.slots.pop(self.active)
            blocked = self.tabs.blockSignals(True)
            self.tabs.removeTab(self.active)
            self.tabs.blockSignals(blocked)
            self.active = -1
        index_new = self._add_slot(slot)
        if self.active < 0:
            self.generation += 1
            self.w._reset_session()
            self.active = index_new
            blocked = self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(index_new)
            self.tabs.blockSignals(blocked)
            self.apply(slot, index_folder=index)
            self._remember_open()
            self._update_tabs()
        else:
            self.activate(index_new, index_folder=index)
        if fresh and save_now:
            self._save(slot, force=True)     # otherwise written by the first autosave (once there is a state)
        proj.add_recent(folder)
        self.w._log(('New project ' if fresh else 'Opened project ') + f'{slot.name} ({folder})')
        return slot

    def save_now(self):
        slot = self.current()
        if slot is None:
            return
        slot.document = self.capture(slot)
        self._save(slot, force=True)
        self.w.statusBar().showMessage(f'Saved {slot.path}', 4000)

    # ------------------------------------------------------------------ autosave / recovery
    def _save(self, slot: Slot, force: bool = False):
        text = json.dumps(slot.document, sort_keys=True, default=str)
        if not force and text == slot.last_text:
            return
        if slot.folder is None and not slot.document.get('scans'):
            try:
                proj.session_file().unlink(missing_ok=True)       # nothing to recover
            except OSError:
                pass
            slot.last_text = text
            return
        slot.last_text = text
        data = dict(slot.document)
        data['saved'] = __import__('datetime').datetime.now().isoformat(timespec='seconds')
        self._writer.submit(slot.path, data)

    def autosave(self):
        if self._switching:
            return
        slot = self.current()
        if slot is not None:
            try:
                slot.document = self.capture(slot)
                self._save(slot)
            except Exception as exc:
                self.w._log(f'Project state not saved: {exc}')
        for error in self._writer.errors():
            self.w._log(f'Project state could not be written: {error}', important=True)

    def _remember_open(self):
        proj.save_state(open=[{'folder': str(s.folder) if s.folder else None, 'id': s.document.get('id')}
                              for s in self.slots],
                        active=max(0, self.active), clean_exit=False)

    def restore_at_start(self) -> bool:
        """Reopen the projects of the last run. Returns True when something was restored."""
        state = proj.load_state()
        crashed = not state.get('clean_exit', True)
        entries = state.get('open') or []
        if entries and all(s.folder is None and not s.document.get('scans') for s in self.slots):
            # an empty unsaved session made at start is replaced by what is restored
            self.slots.clear()
            self.active = -1
            blocked = self.tabs.blockSignals(True)
            while self.tabs.count():
                self.tabs.removeTab(0)
            self.tabs.blockSignals(blocked)
        if state.get('restoring'):
            # The previous start crashed while restoring: do not try again automatically.
            proj.save_state(restoring=False)
            self.ensure_session()
            self.w._log('The last session was not reopened automatically because SPM Studio stopped while '
                        'reopening it. Use Open project… to open it again.', important=True)
            return False
        if not self.reopen_enabled() or not entries:
            self.ensure_session()
            proj.save_state(clean_exit=False)
            return False
        proj.save_state(restoring=True)
        restored = 0
        try:
            for entry in entries:
                folder = entry.get('folder')
                if folder:
                    if not Path(folder).is_dir():
                        continue
                    try:
                        document = proj.load_project(folder)
                    except ValueError:
                        document = None
                    if document is None:
                        continue
                    self._add_slot(Slot(Path(folder), document))
                else:
                    document = proj.read_json(proj.session_file())
                    if document and document.get('scans'):
                        self._add_slot(Slot(None, document))
            if not self.slots:
                self.ensure_session()
                proj.save_state(restoring=False, clean_exit=False)
                return False
            index = max(0, min(int(state.get('active', 0)), len(self.slots) - 1))
            self.active = index
            self.generation += 1
            blocked = self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(index)
            self.tabs.blockSignals(blocked)
            self.apply(self.slots[index])
            restored = len(self.slots)
        finally:
            proj.save_state(restoring=False)
        self._remember_open()
        self._update_tabs()
        slot = self.current()
        what = f'project “{slot.name}”' if slot and slot.folder else 'last session'
        if crashed:
            self.w._log(f'SPM Studio was not closed normally: your {what} has been restored where you were.',
                        important=True)
        self.w.statusBar().showMessage(f'Reopened your {what}' + (f' (+{restored - 1} more project tab(s))'
                                                                  if restored > 1 else ''), 8000)
        return True

    def shutdown(self):
        """Save everything and remember a clean exit (called from closeEvent)."""
        self.timer.stop()
        slot = self.current()
        if slot is not None:
            try:
                slot.document = self.capture(slot)
                self._save(slot, force=True)
            except Exception:
                pass
        self._writer.flush()
        proj.save_state(open=[{'folder': str(s.folder) if s.folder else None, 'id': s.document.get('id')}
                              for s in self.slots if s.folder or s.document.get('scans')],
                        active=max(0, self.active), clean_exit=True)


def _jsonable(value):
    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return {}


def _rebase(doc: dict, old_folder, new_folder) -> dict:
    """Re-express every stored path of ``doc`` for another project folder."""
    conv = lambda t: proj.to_stored_path(proj.from_stored_path(t, old_folder), new_folder)

    def rekey(mapping):
        out = {}
        for text, value in (mapping or {}).items():
            key = proj.key_from_text(text)
            out[proj.key_text((conv(key[0]),) + tuple(key[1:]))] = value
        return out
    doc = json.loads(json.dumps(doc, default=str))
    state = doc.get('state') or {}
    doc['scans'] = [conv(t) for t in doc.get('scans', [])]
    doc['removed'] = [conv(t) for t in doc.get('removed', [])]
    doc['current'] = conv(doc['current']) if doc.get('current') else None
    state['views'] = {conv(k): v for k, v in (state.get('views') or {}).items()}
    state['styles'] = rekey(state.get('styles'))
    state['pipelines'] = rekey(state.get('pipelines'))
    state['masks'] = rekey(state.get('masks'))
    state['profiles'] = {conv(k): v for k, v in (state.get('profiles') or {}).items()}
    state['pending_profiles'] = [conv(p) for p in state.get('pending_profiles', [])]
    doc['state'] = state
    return doc
