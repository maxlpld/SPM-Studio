"""Installer self-test (``python -m spm_studio --smoke-test``), offscreen, disposable dirs.

Exercises the parts most likely to break on a new machine: every bundled theme,
the main menus, the assistant panel and setup dialog, the Results options and the
Export-panel renderer used by the lattice / molecule figures (SVG, PDF, PNG).
Nothing touches the user's data; no network, no hardware, no AI provider.
"""
from __future__ import annotations
import sys
import tempfile
import traceback
from pathlib import Path

import numpy as np


def _check(name, fn, failures):
    try:
        fn()
        print(f'SMOKE ok    {name}', flush=True)
    except Exception:
        failures.append(name)
        print(f'SMOKE FAIL  {name}\n{traceback.format_exc()}', file=sys.stderr, flush=True)


def run(win) -> int:
    from PySide6.QtWidgets import QApplication
    failures = []
    app = QApplication.instance()

    def themes():
        from spm_studio.core import paths
        names = [p.stem for p in sorted((paths.customization_dir() / 'themes').glob('*.json'))]
        assert 'graphite' in names and 'porcelain' in names, names
        for name in names + ['graphite']:
            win._apply_theme(name)
            app.processEvents()

    def menus():
        titles = [a.text().replace('&', '') for a in win.menuBar().actions()]
        for wanted in ('File', 'Scan', 'Selection', 'Analysis', 'View', 'Settings', 'Help'):
            assert wanted in titles, titles
        assert win._theme_menu.actions(), 'theme menu empty'
        # v0.0.5: the menus only carry the shortcuts; the bar itself is hidden.
        assert not win.menuBar().isVisible(), 'menu bar should be hidden'
        assert win.windowTitle() == 'SPM Studio', win.windowTitle()
        assert not win.settings_button.icon().isNull(), 'gear button has no icon'

    def settings():
        from spm_studio.ui.settings_dialog import SettingsDialog, PAGES
        from spm_studio.core import paths
        dialog = SettingsDialog(win)
        for key, _label, _icon in PAGES:
            dialog.show_page(key); app.processEvents()
        for index in range(dialog.kind_combo.count()):
            dialog.kind_combo.setCurrentIndex(index); app.processEvents()
            assert dialog.items.count() > 0, dialog.kind_combo.itemData(index)
        dialog.close(); dialog.deleteLater()
        for folder in ('profiles', 'export_presets', 'themes', 'colormaps', 'plot_styles', 'shortcuts'):
            assert (paths.customization_dir() / folder / 'README.md').is_file(), folder
        assert (paths.scripts_dir() / 'README.md').is_file()
        assert not (paths.customization_dir() / 'profiles' / 'KPFM_v7.json').exists()
        win.log_dock.show(); app.processEvents()
        assert win.log_dock.spm_close_button.width() >= 26
        win.log_dock.hide()

    def assistant():
        win.ai_dock.show(); app.processEvents()
        win.ai_dock.setFloating(True); app.processEvents()
        win.ai_dock.setFloating(False); app.processEvents()
        win.ai_dock.history = [{'role': 'user', 'content': 'Hello'},
                               {'role': 'assistant', 'content': '**Bold** and `code`\n\n```python\nprint(1)\n```'}]
        win.ai_dock.render()
        assert 'Bold' in win.ai_dock.conversation.toPlainText()
        win.ai_dock.history = []
        win.ai_dock.render()
        win.ai_dock._set_busy(True, 'smoke'); app.processEvents(); win.ai_dock._set_busy(False)
        assert win.ai_dock.tools_button is not None
        from spm_studio.ai.config import spm_context_file
        from spm_studio.core import paths
        # The generated prompt is UTF-8. Without an explicit encoding,
        # Windows users with a cp1252 locale fail this installer smoke test
        # on perfectly valid Unicode punctuation (e.g. U+201D).
        assert str(paths.scripts_dir()) in spm_context_file(paths.scripts_dir()).read_text(encoding='utf-8')

    def live_tools():
        from spm_studio.core import paths
        folder = paths.scripts_dir() / 'smoke_hello_tool'
        folder.mkdir(exist_ok=True)
        (folder / 'module.json').write_text('{"api_version":"1.0","id":"smoke_hello_tool","name":"Smoke hello",'
            '"version":"1.0.0","description":"self-test","category":"Examples","mode":"analysis",'
            '"status":"experimental","entrypoint":"module:run","interaction":"none",'
            '"snapshot_channels":"selected","requires":[],"parameters":{}}')
        (folder / 'module.py').write_text('def run(ctx):\n    ctx.log("hello")\n')
        win._check_scripts_folder(); win._check_scripts_folder()
        assert 'smoke_hello_tool' in win.modules, 'new tool not detected live'
        import shutil
        shutil.rmtree(folder)
        from spm_studio.ai.setup_ui import SetupDialog
        dialog = SetupDialog(win.ai_dock)
        for i in range(dialog.mode.count()):
            dialog.mode.setCurrentIndex(i); app.processEvents()
        # v0.0.7: Quick start cards + Advanced page
        assert dialog.nav.count() == 2 and len(dialog.cards) == 6
        for row in (1, 0):
            dialog.nav.setCurrentRow(row); app.processEvents()
        from spm_studio.ai.pi_wizard import PiSetupWizard
        from spm_studio.ai import pi_setup, platform_util, judge_proxy, cli_agents  # noqa: F401
        wizard = PiSetupWizard(win.ai_dock)
        for i in range(wizard.pages.count()):
            wizard.pages.setCurrentIndex(i); app.processEvents()
        wizard.close(); wizard.deleteLater()
        proxy = judge_proxy.JudgeProxy(port=0).start(); proxy.stop()
        from spm_studio.ui.update_dialog import UpdateDialog
        upd = UpdateDialog(win, {'repository': 'owner/repo', 'current': '0.0.1', 'latest': '9.9.9', 'tag': 'v9.9.9',
                                 'update': True, 'url': '', 'archive': '', 'source': 'releases',
                                 'notes': [{'version': '9.9.9', 'notes': '- smoke', 'published': ''}]})
        upd._set_progress(40, 'Installing'); upd._toggle_details(True); upd._toggle_details(False)
        app.processEvents()
        upd.close(); upd.deleteLater()
        assert platform_util.hardware()['os']
        dialog.close(); dialog.deleteLater()
        win.ai_dock.hide()

    def options():
        from spm_studio.ui.plot_options import PlotOptions, script_formats
        dialog = PlotOptions(win, win.settings)
        dialog.close(); dialog.deleteLater()
        assert script_formats(win.settings)

    def script_figures():
        from spm_studio.core.script_figures import export_scan_figure, scan_display_style
        rng = np.random.default_rng(1)
        data = rng.normal(size=(80, 96))
        cfg = {'schema_version': 1, 'viewer_config': {'enabled': True, 'channels': {'Z': {
            'colormap': 'viridis', 'range_mode': 'percentile', 'low': 1., 'high': 99., 'gamma': 1.,
            'scale_bar': True, 'colorbar': True, 'title': 'Z'}}}}
        style = scan_display_style(cfg, 'Z')
        assert style.colormap == 'viridis'
        lattice = {'basis_local_nm': [[1.0, 0.5], [0.0, 0.86]], 'gamma_deg': 60.0,
                   'roi_geometry': {'size_nm': [9.6, 8.0]}, 'vector_colors': ['#16d8f5', '#fbb748'],
                   'vector_legend_corner': 'top_left'}

        def decorate(painter, rect):
            from PySide6.QtGui import QColor
            painter.fillRect(rect.adjusted(rect.width() * .45, rect.height() * .45,
                                           -rect.width() * .45, -rect.height() * .45), QColor('#ff3355'))
        with tempfile.TemporaryDirectory() as tmp:
            scan = Path(tmp) / 'synthetic.sxm'
            scan.write_bytes(b'smoke')
            out = export_scan_figure(Path(tmp) / 'figure', scan_path=scan, data=data, size_nm=(9.6, 8.0),
                                     channel='Z', unit='m', plot_config=cfg, formats=('svg', 'pdf', 'png'),
                                     style=style, lattice=lattice, decorate=decorate)
            assert [p.suffix for p in out] == ['.svg', '.pdf', '.png'], out
            assert all(p.is_file() and p.stat().st_size > 500 for p in out)
            assert '<svg' in out[0].read_text(encoding='utf8', errors='replace')[:2000]

    def results_view():
        from spm_studio.ui.result_view import _render_svg
        with tempfile.TemporaryDirectory() as tmp:
            svg = Path(tmp) / 'x.svg'
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10"><rect width="20" height="10" fill="red"/></svg>')
            image = _render_svg(svg, 200)
            assert image.width() == 200

    def documents():
        # v0.0.8: LaTeX editor, presentation editor, templates and the figure hand-over.
        from spm_studio.core import paths
        from spm_studio.documents import latex_project, templates, deck
        assert templates.find('latex', 'Article') is not None and templates.find('slides', 'Clean_Light') is not None
        for folder in ('latex_templates', 'presentation_templates'):
            assert (paths.customization_dir() / folder / 'README.md').is_file(), folder
        assert not win.latex_button.isVisible() or win.latex_button.text() == 'LaTeX'
        with tempfile.TemporaryDirectory() as tmp:
            svg = Path(tmp) / 'figure.svg'
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10"><rect width="20" '
                           'height="10" fill="red"/></svg>')
            project = latex_project.create_project(tmp, 'Smoke paper', templates.find('latex', 'Article').path)
            editor = win.documents.open_latex(project)
            editor.auto_button.setChecked(False)
            app.processEvents()
            rel = editor.insert_figure([svg], 'Smoke')
            assert (project / rel).is_file() and rel in editor.editor.toPlainText()
            editor.close(); app.processEvents()
            file = deck.create_project(tmp, 'Smoke talk', template=templates.load_slides_template('Scientific_Talk'))
            slides = win.documents.open_slides(file)
            app.processEvents()
            slides.add_figure([svg], new_slide=True, title='Smoke')
            slides.add_latex(r'$x^2$', x=48, y=300, w=200, h=40)
            slides.add_text('Smoke', x=48, y=360, w=200, h=40)
            app.processEvents()
            assert slides.save() and len(deck.load(file)['slides']) == 6
            slides.close(); app.processEvents()

    for name, fn in (('themes', themes), ('menus', menus), ('settings window', settings),
                     ('assistant panel', assistant),
                     ('results options', options), ('live tool detection', live_tools), ('export-panel figures', script_figures),
                     ('svg result preview', results_view), ('LaTeX and presentation editors', documents)):
        _check(name, fn, failures)
    print('SMOKE ' + ('FAILED: ' + ', '.join(failures) if failures else 'PASSED'), flush=True)
    return 1 if failures else 0
