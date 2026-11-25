"""Render screenshots of the main SPM Studio windows and dialogs (offscreen) for design review.

    python tools/ui_screenshots.py OUTPUT_DIR [--size 1440x900]

Uses disposable settings/data folders, the bundled tutorial scans, no network, no hardware. Every shot is
independent: a failing one is reported and the others continue. Used by the "UI screenshots" workflow.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback
from pathlib import Path


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    out = Path(argv[0] if argv else 'ui-screenshots').resolve()
    size = (1440, 900)
    if '--size' in argv:
        w, h = argv[argv.index('--size') + 1].lower().split('x')
        size = (int(w), int(h))
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix='spm-shots-'))
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ['HOME'] = str(tmp)
    os.environ['XDG_CONFIG_HOME'] = str(tmp / 'config')
    os.environ['XDG_DATA_HOME'] = str(tmp / 'data')
    os.environ['XDG_CACHE_HOME'] = str(tmp / 'cache')
    os.environ['SPM_STUDIO_NO_UPDATE_CHECK'] = '1'
    os.environ['SPM_STUDIO_NO_ONBOARDING'] = '1'
    os.environ['SPM_STUDIO_BETA_API'] = 'http://127.0.0.1:9'
    os.environ['SPM_STUDIO_USE_GH_CLI'] = '0'
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication(['spm-shots'])
    app.setApplicationName('SPM Studio')
    app.setOrganizationName('SPM Studio')
    from spm_studio.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(*size)
    win.show()
    failures = []
    modal_count = [0]

    def close_modals():
        """A dialog opened with exec() would block the run: photograph it, then close it."""
        widget = app.activeModalWidget()
        if widget is not None:
            modal_count[0] += 1
            try:
                widget.grab().save(str(out / f'99_modal_{modal_count[0]:02d}.png'))
                print('modal closed:', widget.windowTitle(), flush=True)
            except Exception:
                pass
            widget.close()
            try:
                widget.reject()
            except Exception:
                pass
    watchdog = QTimer()
    watchdog.timeout.connect(close_modals)
    watchdog.start(1500)

    def pump(seconds=.3):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(.01)

    def shot(name, widget=None):
        pump(.25)
        widget = widget or win
        pix = widget.grab()
        pix.save(str(out / f'{name}.png'))
        print('shot', name, pix.width(), 'x', pix.height(), flush=True)

    def step(name, fn):
        try:
            fn()
        except Exception:
            failures.append(name)
            print(f'FAILED {name}\n{traceback.format_exc()}', flush=True)

    def wait_scan(timeout=40):
        end = time.monotonic() + timeout
        while win.scan is None and time.monotonic() < end:
            pump(.1)
        pump(1.0)
        return win.scan is not None

    themes = ['light_studio', 'dark_studio', 'graphite', 'porcelain'] + [t for t in os.environ.get('SPM_SHOT_THEMES', '').split(',') if t]

    def empty():
        for theme in themes:
            win._apply_theme(theme)
            shot(f'01_main_empty_{theme}')

    def with_scan():
        win.open_tutorial_scans()
        pump(1)
        from spm_studio.tutorial import dataset
        folder = dataset.prepare_workspace()
        win._load_file(str(folder / dataset.MAIN))
        assert wait_scan(), 'scan did not load'
        for theme in themes:
            win._apply_theme(theme)
            shot(f'02_main_scan_{theme}')
        win._apply_theme('graphite')

    def tools_panel():
        win.show_image_tools() if hasattr(win, 'show_image_tools') else None
        panel = getattr(win, 'module_panel', None)
        combo = None
        for name in ('module_combo', 'combo', 'modules'):
            combo = getattr(panel, name, None)
            if combo is not None and hasattr(combo, 'count'):
                break
        if combo is not None and combo.count() > 1:
            combo.setCurrentIndex(1)
        shot('03_main_tools')
        for theme in themes[1:2]:
            win._apply_theme(theme)
            shot(f'03_main_tools_{theme}')
        win._apply_theme('graphite')

    def logs():
        win.log_dock.show()
        shot('04_main_logs')
        win.log_dock.hide()

    def settings():
        from spm_studio.ui.settings_dialog import SettingsDialog, PAGES
        for theme in themes[:2]:
            win._apply_theme(theme)
            dialog = SettingsDialog(win)
            dialog.resize(960, 680)
            dialog.show()
            for key, _label, _icon in PAGES:
                dialog.show_page(key)
                shot(f'05_settings_{key}_{theme}', dialog)
            dialog.close()
        win._apply_theme('graphite')

    def messages():
        for kind, icon in (('info', QMessageBox.Icon.Information), ('question', QMessageBox.Icon.Question),
                           ('warning', QMessageBox.Icon.Warning)):
            box = QMessageBox(icon, 'SPM Studio', 'The export finished. 3 files were written to the results folder.',
                              QMessageBox.StandardButton.Ok | (QMessageBox.StandardButton.Cancel
                                                               if kind == 'question' else QMessageBox.StandardButton.NoButton),
                              win)
            box.show()
            shot(f'06_message_{kind}', box)
            box.close()
        from spm_studio.shared.dialogs import MessageDialog
        box = MessageDialog(QMessageBox.Icon.Critical, 'Script failed', 'The script stopped with an error.',
                            QMessageBox.StandardButton.Ok, win)
        box.setDetailedText('Traceback (most recent call last):\n  File "module.py", line 12\nValueError: example')
        box.show()
        shot('06_message_critical', box)
        box.close()

    def readme():
        from spm_studio.ui.settings_dialog import GuideDialog
        readme = Path(__file__).resolve().parents[1] / 'src' / 'spm_studio' / 'builtin_modules' / 'README.md'
        for theme in themes[:2]:
            win._apply_theme(theme)
            dialog = GuideDialog(readme, 'Read me — tools', win)
            dialog.show()
            shot(f'07_readme_{theme}', dialog)
            dialog.close()
        win._apply_theme('graphite')

    def documents():
        for name, opener in (('todo', 'open_todo'), ('latex', 'open_latex_editor'), ('slides', 'open_slides_editor')):
            for theme in themes[:2]:
                win._apply_theme(theme)
                doc = getattr(win, opener)()
                pump(1)
                target = doc if doc is not None and hasattr(doc, 'grab') else app.activeWindow() or win
                try:
                    if name != 'todo':                 # the to-do keeps its compact post-it size
                        target.resize(1280, 800)
                except Exception:
                    pass
                shot(f'08_{name}_{theme}', target)
                try:
                    target.close()
                except Exception:
                    pass
        win._apply_theme('graphite')

    def print3d():
        win.open_print3d()
        dialog = win._print3d_dialog
        dialog.resize(1280, 860)
        dialog.update_preview()
        shot('09_print3d', dialog)
        dialog.close()

    def tutorial():
        from spm_studio.tutorial.ui import WelcomePanel
        panel = WelcomePanel(win) if 'parent' in WelcomePanel.__init__.__code__.co_varnames else None
        if panel is not None:
            panel.show()
            shot('10_tutorial_welcome', panel)
            panel.close()

    def projects_and_selection():
        # v0.0.20: two project tabs, several scans picked with Shift + Enter
        from spm_studio.tutorial import dataset
        import shutil
        source = dataset.prepare_workspace()
        second = tmp / 'Second project'
        second.mkdir(exist_ok=True)
        for name in dataset.FILES[:2]:
            shutil.copy2(source / name, second / name)
        win.projects.open_folder(source)
        pump(1.5)
        win.projects.open_folder(second)
        pump(1.5)
        win.projects.activate(0)
        assert wait_scan(), 'scan did not load'
        from PySide6.QtCore import QItemSelectionModel
        b = win.browser
        b.begin_marking()
        for row in (0, 2):
            b.files.selectionModel().setCurrentIndex(b.files.model().index(row, 0),
                                                     QItemSelectionModel.SelectionFlag.NoUpdate)
            b.toggle_mark_current()
        b.end_marking()
        pump(1.0)
        for theme in themes[:2]:
            win._apply_theme(theme)
            shot(f'12_projects_multiselect_{theme}')
        win.browser.clear_marks()
        win._apply_theme('graphite')

    def channel_switch():
        # v0.0.20: right after a click on another channel (must show that channel or an empty frame)
        if win.scan is None:
            return
        names = list(win.scan.channels)[:3]
        win.inspector.set_visible_channels(names)
        pump(1.5)
        win.inspector.channel.setCurrentText(names[1])
        shot('13_channel_switch_immediate')
        pump(1.0)
        shot('13_channel_switch_done')

    def compare():
        from spm_studio.ui.research_compare import CompareDialog

        class Store:
            def runs(self):
                out = []
                for i, (name, a) in enumerate((('KBr001_008', .401), ('KBr001_009', .396), ('KBr001_015', .409),
                                               ('KBr001_021', .404), ('KBr001_030', .398))):
                    out.append({'result_id': f'r{i}', 'scan_id': name, 'source_path': f'/data/{name}.sxm',
                                'module_id': 'lattice_measurements', 'status': 'completed',
                                'created_at': f'2026-11-2{i}T10:00', 'run_folder': '/tmp',
                                'measurements': [{'key': 'a (nm)', 'table': 'Lattice', 'value': a,
                                                  'row': {'type': 'KBr'}},
                                                 {'key': 'angle (deg)', 'table': 'Lattice', 'value': 90 + i * .3,
                                                  'row': {'type': 'KBr'}}]})
                return out
        for theme in themes[:2]:
            win._apply_theme(theme)
            dialog = CompareDialog(win, store=Store())
            dialog.resize(1180, 720)
            dialog.show()
            shot(f'14_compare_{theme}', dialog)
            dialog.close()
        dialog = CompareDialog(win, store=type('S', (), {'runs': lambda self: []})())
        dialog.show()
        shot('14_compare_empty', dialog)
        dialog.close()
        win._apply_theme('graphite')

    def theme_studio_window():
        from spm_studio import theme_studio
        studio = theme_studio.instance()
        if studio is None:
            return
        w = studio.open()
        w.resize(1180, 760)
        shot('15_theme_studio', w)
        w.close()

    def narrow():
        win.resize(1100, 720)
        shot('11_main_narrow_1100x720')
        win.resize(*size)

    for name, fn in (('empty', empty), ('with scan', with_scan), ('tools panel', tools_panel), ('logs', logs),
                     ('settings', settings), ('messages', messages), ('readme', readme), ('documents', documents),
                     ('3D print', print3d), ('tutorial', tutorial), ('projects', projects_and_selection),
                     ('channel switch', channel_switch), ('compare', compare), ('theme studio', theme_studio_window),
                     ('narrow', narrow)):
        step(name, fn)
    print('FAILED SHOTS:', failures if failures else 'none', flush=True)
    if os.environ.get('SPM_SHOTS_TO_LOG') == '1':
        # Pictures also as base64 text in the job log (for reviewers who cannot download artifacts).
        import base64
        from PySide6.QtGui import QImage
        for png in sorted(out.glob('*.png')):
            image = QImage(str(png))
            jpg = png.with_suffix('.jpg')
            image.save(str(jpg), 'JPG', 82)
            data = base64.b64encode(jpg.read_bytes()).decode()
            print(f'=====BEGIN {jpg.name}', flush=True)
            for i in range(0, len(data), 4000):
                print('B64:' + data[i:i + 4000])
            print(f'=====END {jpg.name}', flush=True)
    QTimer.singleShot(0, app.quit)
    app.exec()
    os._exit(0)


if __name__ == '__main__':
    raise SystemExit(main())
