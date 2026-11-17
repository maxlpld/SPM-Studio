"""SPM Studio 0.0.8: LaTeX editor, presentation editor, Overleaf, templates, assistant actions.

The first part needs no Qt (models, templates, logs, protocol, Overleaf through a local Git
repository). The GUI part runs when PySide6 is installed (offscreen); compilation tests run only
when a TeX installation is found.
"""
import json
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache'))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    (tmp_path / 'home').mkdir()
    from spm_studio.core import paths
    paths.install_factory_customization()
    paths.install_factory_templates()
    paths.ensure_guides()
    return tmp_path


def _tex_available():
    from spm_studio.documents import tex
    return tex.best_engine('latexmk') is not None


# ============================================================================ settings
def test_settings_defaults_off_and_roundtrip(home):
    from spm_studio.documents import settings
    conf = settings.load()
    assert conf['latex_enabled'] is False and conf['slides_enabled'] is False
    assert not settings.any_enabled(conf)
    assert settings.latex_root(conf).name == 'LaTeX' and settings.slides_root(conf).name == 'Presentations'
    settings.update(latex_enabled=True, latex_engine='nonsense', latex_autocompile_delay_ms=800, unknown=1)
    conf = settings.load()
    assert conf['latex_enabled'] and conf['latex_engine'] == 'latexmk' and conf['latex_autocompile_delay_ms'] == 800
    assert 'unknown' not in json.loads((home / 'config' / 'spm-studio-ai' / 'documents.json').read_text())
    settings.add_recent('latex', home)
    assert settings.recent('latex') == [home]


# =========================================================================== templates
def test_factory_templates_guides_and_library(home):
    from spm_studio.core import library, paths
    from spm_studio.documents import templates
    custom = paths.customization_dir()
    for folder in ('latex_templates', 'presentation_templates'):
        assert (custom / folder / 'README.md').is_file()
        assert paths.guide_for(custom / folder) == custom / folder / 'README.md'
    latex = {t.name for t in templates.list_templates('latex')}
    assert {'Article', 'Scientific_Paper', 'Beamer_Talk', 'Report_Thesis', 'Lab_Notes.tex'} <= latex
    slides = {t.name for t in templates.list_templates('slides')}
    assert {'Clean_Light.json', 'Graphite_Dark.json', 'Scientific_Talk.json', 'Classic_4x3.json'} <= slides
    for kind in ('latex_templates', 'slide_templates'):
        items = library.list_items(kind)
        assert items and all(i.valid for i in items), [(i.name, i.detail) for i in items if not i.valid]
        assert 'README.md' not in {i.name for i in items}
        assert library.guide(kind) is not None
    # removed factory templates stay removed
    library.remove_item('latex_templates', 'Lab_Notes.tex')
    paths.install_factory_templates()
    assert not (custom / 'latex_templates' / 'Lab_Notes.tex').exists()


def test_guide_examples_are_valid(tmp_path):
    from spm_studio.documents import templates
    text = (ROOT / 'customization' / 'presentation_templates' / 'README.md').read_text(encoding='utf8')
    blocks = [json.loads(b) for b in re.findall(r'```json\r?\n(.*?)```', text, re.S)]
    assert blocks
    tmp = tmp_path
    for n, block in enumerate(blocks):
        path = tmp / f'guide_example_{n}.json'
        path.write_text(json.dumps(block), encoding='utf8')
        templates.validate_slides(path)
    latex_guide = (ROOT / 'customization' / 'latex_templates' / 'README.md').read_text(encoding='utf8')
    for block in re.findall(r'```json\r?\n(.*?)```', latex_guide, re.S):
        assert 'main' in json.loads(block)


def test_library_imports_latex_projects_zips_and_slide_templates(home, tmp_path):
    from spm_studio.core import library
    from spm_studio.documents import templates
    project = tmp_path / 'My Group Paper'
    project.mkdir()
    (project / 'paper.tex').write_text('\\documentclass{article}\\begin{document}Hi\\end{document}\n')
    (project / '.spm_build').mkdir()
    installed = library.import_path('latex_templates', project)
    assert installed[0].is_dir() and (installed[0] / 'template.json').is_file()
    assert json.loads((installed[0] / 'template.json').read_text())['main'] == 'paper.tex'
    # an Overleaf "Download source" zip
    archive = tmp_path / 'overleaf.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('main.tex', '\\documentclass{article}\\begin{document}x\\end{document}')
        z.writestr('figures/a.txt', 'x')
    installed = library.import_path('latex_templates', archive)
    assert (installed[0] / 'main.tex').is_file()
    # single .tex files, and junk is refused
    single = tmp_path / 'Memo.tex'
    single.write_text('\\documentclass{letter}\n')
    library.import_path('latex_templates', single)
    bad = tmp_path / 'bad.tex'
    bad.write_text('no class')
    with pytest.raises(library.LibraryError):
        library.import_path('latex_templates', bad)
    # presentation templates
    tpl = tmp_path / 'Talk.json'
    tpl.write_text(json.dumps({'format': 'spm-slides-template-v1', 'name': 'Talk', 'size': '4:3',
                               'theme': {'accent_color': '#123456'}}))
    library.import_path('slide_templates', tpl)
    assert templates.find('slides', 'Talk') is not None
    tpl.write_text(json.dumps({'format': 'spm-slides-template-v1', 'theme': {'accent_color': 'red'}}))
    with pytest.raises(library.LibraryError):
        library.import_path('slide_templates', tpl, on_conflict='rename')
    assert library.detect_kind(single) == 'latex_templates'
    # export → import as pack
    pack = library.export_items('latex_templates', ['Article'], tmp_path / 'pack')
    library.remove_item('latex_templates', 'Article')
    library.import_path('latex_templates', pack)
    assert templates.find('latex', 'Article') is not None
    # edit template.json through the library
    text = library.read_text('latex_templates', 'Article')
    library.save_text('latex_templates', 'Article', text.replace('"Article"', '"Article (edited)"'))
    assert templates.find('latex', 'Article (edited)') is not None
    assert library.duplicate_item('latex_templates', 'Article', 'Article_copy').is_dir()


# ================================================================================ LaTeX
def test_projects_from_every_template_and_figure_insertion(home, tmp_path):
    from spm_studio.documents import latex_project, templates, tex
    root = tmp_path / 'projects'
    for template in templates.list_templates('latex'):
        project = latex_project.create_project(root, f'P {template.name}', template.path, author='Ada')
        main = tex.find_main_file(project)
        assert main is not None and (project / 'figures').is_dir()
        assert not (project / 'template.json').exists()
        text = main.read_text(encoding='utf8')
        assert '{{' not in text.replace('{{figures/}}', ''), template.name
    project = latex_project.create_project(root, 'Paper', templates.find('latex', 'Article').path, author='Ada')
    assert (latex_project.create_project(root, 'Paper').name) == 'Paper (2)'
    text = (project / 'main.tex').read_text()
    assert '\\author{ Ada }' in text and '\\title{ Paper }' in text
    figure = tmp_path / 'scan_Z fwd.pdf'
    figure.write_bytes(b'%PDF-1.4\n')
    placed = latex_project.add_figure(project, figure)
    assert placed == project / 'figures' / 'scan_Z_fwd.pdf'
    assert latex_project.add_figure(project, figure) == placed          # same file: not duplicated
    cursor = text.index('Conclude.')
    new, start, end = latex_project.insert_figure_text(text, cursor, 'figures/scan_Z_fwd.pdf', 'Topography 50%')
    block = new[start:end]
    assert '\\includegraphics[width=0.8\\linewidth]{figures/scan_Z_fwd.pdf}' in block
    assert '\\caption{Topography 50\\%}' in block and '\\label{fig:scan_Z_fwd}' in block
    assert new.index(block) < new.index('Conclude.')
    # cursor in the preamble → before \end{document}; graphicx added when missing
    bare = '\\documentclass{article}\n\\begin{document}\nText\n\\end{document}\n'
    new, start, end = latex_project.insert_figure_text(bare, 5, 'figures/a.png')
    assert '\\usepackage{graphicx}' in new and new.index('\\includegraphics') < new.index('\\end{document}')
    beamer = '\\documentclass{beamer}\n\\begin{document}\n\\end{document}\n'
    new, *_ = latex_project.insert_figure_text(beamer, 0, 'figures/a.pdf', 'Result')
    assert '\\begin{frame}{Result}' in new and '\\usepackage{graphicx}' not in new
    assert [o.title for o in latex_project.outline(text)][:2] == ['Introduction', 'Methods']
    assert 'binnig1982' in latex_project.bib_keys(project)
    assert 'eq:tunnel' in latex_project.labels([text])


def test_zip_roundtrip_and_copy(home, tmp_path):
    from spm_studio.documents import latex_project
    project = latex_project.create_project(tmp_path, 'Round')
    (project / '.spm_build').mkdir()
    (project / '.spm_build' / 'main.log').write_text('log')
    archive = latex_project.export_zip(project, tmp_path / 'out')
    names = zipfile.ZipFile(archive).namelist()
    assert 'main.tex' in names and not any('.spm_build' in n for n in names)
    back = latex_project.import_zip(archive, tmp_path / 'imported')
    assert (back / 'main.tex').is_file()
    evil = tmp_path / 'evil.zip'
    with zipfile.ZipFile(evil, 'w') as z:
        z.writestr('../escape.tex', 'x')
    with pytest.raises(latex_project.ProjectError):
        latex_project.import_zip(evil, tmp_path / 'imported')
    copy = latex_project.copy_project(project, tmp_path / 'elsewhere', 'Round v2')
    assert (copy / 'main.tex').is_file() and not (copy / '.spm_build').exists()


def test_log_parser_and_word_count():
    from spm_studio.documents import tex
    log = ('(./main.tex\n./main.tex:12: Undefined control sequence.\nl.12 \\foo\n             bar\n'
           'LaTeX Warning: Reference `fig:x\' on page 1 undefined on input line 30.\n'
           'Overfull \\hbox (12.3pt too wide) in paragraph at lines 40--42\n'
           './sections/intro.tex:3: Missing $ inserted.\n')
    summary = tex.parse_log(log)
    assert [(e.file, e.line) for e in summary.errors] == [('main.tex', 12), ('sections/intro.tex', 3)]
    assert summary.errors[0].context.startswith('\\foo')
    assert summary.warnings and summary.warnings[0].line == 30
    assert summary.badboxes and summary.badboxes[0].line == 40
    plain = tex.parse_log('! LaTeX Error: File `missing.sty\' not found.\n\nl.4 \\usepackage\n')
    assert plain.errors and plain.errors[0].line == 4
    assert tex.word_count('\\begin{document}Hello world, $x^2$ \\textbf{bold} % no\n\\end{document}') == 3
    assert tex.needs_rerun('LaTeX Warning: Label(s) may have changed. Rerun to get cross-references right.')
    steps = tex.compile_steps('pdflatex', Path('main.tex'))
    assert steps[0][-1] == 'main.tex' and '-output-directory=.spm_build' in steps[0]


@pytest.mark.skipif(not _tex_available(), reason='no TeX installation')
def test_templates_compile(home, tmp_path):
    from spm_studio.documents import latex_project, templates, tex
    for name in ('Article', 'Beamer_Talk'):
        project = latex_project.create_project(tmp_path, name, templates.find('latex', name).path)
        for step in tex.compile_steps(tex.best_engine('latexmk'), Path('main.tex')):
            subprocess.run(step, cwd=project, capture_output=True, timeout=240,
                           env={**os.environ, 'PATH': tex.search_path()})
        assert (project / tex.BUILD_DIR / 'main.pdf').is_file(), name
        log = (project / tex.BUILD_DIR / 'main.log').read_text(errors='replace')
        assert not tex.parse_log(log).errors, name


def test_save_project_and_deck_as_templates(home, tmp_path):
    from spm_studio.documents import latex_project, templates, deck
    project = latex_project.create_project(tmp_path, 'Thesis', templates.find('latex', 'Report_Thesis').path)
    (project / 'figures' / 'big.png').write_bytes(b'png')
    saved = templates.save_latex_template(project, 'My thesis')
    assert (saved / 'template.json').is_file() and (saved / 'chapters' / 'methods.tex').is_file()
    assert not (saved / 'figures' / 'big.png').exists()
    assert templates.find('latex', 'My thesis') is not None
    d = deck.new_deck('Talk', template=templates.load_slides_template('Graphite_Dark'))
    file = templates.save_slides_template(d, 'Night talk', include_slides=False)
    assert templates.load_slides_template('Night talk')['theme']['background_color'] == '#121417'
    assert file.suffix == '.json'


# ========================================================================== presentation
def test_deck_model_roundtrip_media_and_archives(home, tmp_path):
    from spm_studio.documents import deck, templates
    template = templates.load_slides_template('Scientific_Talk')
    file = deck.create_project(tmp_path, 'Group meeting', template=template)
    assert file == tmp_path / 'Group meeting' / 'Group meeting.spmdeck' and (file.parent / 'media').is_dir()
    d = deck.load(file)
    assert len(d['slides']) == 5 and d['theme']['title_bar'] is True and d['width'] == 960 and d['height'] == 540
    assert 'Group meeting' in deck.plain_text(d['slides'][0]['items'][0]['html'])
    assert len({i['id'] for s in d['slides'] for i in s['items']}) == sum(len(s['items']) for s in d['slides'])
    png = tmp_path / 'scan Z.png'
    png.write_bytes(b'\x89PNG')
    rel = deck.add_media(file.parent, png)
    assert rel == 'media/scan_Z.png' and deck.add_media(file.parent, png) == rel
    assert deck.media_kind('a.GIF') == 'gif' and deck.media_kind('a.mp4') == 'video'
    d['slides'].append(deck.new_slide('two_columns', d['theme'], (960, 540), title='Two'))
    d['slides'][-1]['items'].append(deck.make_item('image', 10, 10, 100, 80, src=rel))
    d['slides'][-1]['items'].append(deck.make_item('latex', 10, 100, 300, 60, source=r'$x^2$'))
    deck.save(d, file)
    again = deck.load(file)
    assert again['slides'][-1]['items'][-2]['src'] == rel
    outline = deck.outline(again)
    assert outline[-1]['text'][-1] == 'LaTeX: $x^2$' and outline[-1]['items'][0]['role'] == 'title'
    archive = deck.export_zip(file, tmp_path / 'share')
    imported = deck.import_zip(archive, tmp_path / 'colleague')
    assert (imported.parent / rel).is_file() and deck.load(imported)['title'] == 'Group meeting'
    copy = deck.copy_project(file, tmp_path / 'copies', 'Group meeting v2')
    assert copy.name == 'Group meeting v2.spmdeck' and deck.load(copy)['title'] == 'Group meeting v2'
    with pytest.raises(deck.DeckError):
        deck.validate({'format': 'other'})
    for layout in deck.LAYOUTS:
        slide = deck.new_slide(layout, d['theme'], (960, 720))
        assert all(0 <= i['x'] <= 960 and i['y'] + i['h'] <= 720 + 1 for i in slide['items']), layout


# ============================================================================= protocol
def test_assistant_protocol():
    from spm_studio.documents import protocol
    text = ('Sure. <spm-doc>{"app": "latex", "action": "read"}</spm-doc>\n'
            '<spm-doc>{"app": "latex", "action": "format_disk"}</spm-doc>'
            '<spm-doc>{"app": "slides", "action": "add_slide", "title": "Results", "slide": 2, "x": "bad", '
            '"after": 1}</spm-doc><spm-doc>not json</spm-doc>')
    requests = protocol.parse_requests(text)
    assert [r['action'] for r in requests] == ['read', 'add_slide']
    assert requests[1] == {'app': 'slides', 'action': 'add_slide', 'title': 'Results', 'slide': 2, 'after': 1}
    assert protocol.needs_followup(requests, [(requests[0], 'x')])
    write = [{'app': 'latex', 'action': 'insert', 'text': 'x'}]
    assert not protocol.needs_followup(write, [(write[0], 'Inserted')])
    assert protocol.needs_followup(write, [(write[0], 'ERROR: no project')])
    message = protocol.result_message([(requests[0], 'content')])
    assert protocol.is_result_message(message) and 'not instructions' in message
    assert protocol.display_text('user', message).startswith('*✎ Editor: LaTeX: read')
    assert '<spm-doc>' not in protocol.display_text('assistant', text)
    note = 'Please fix it' + protocol.context_note('LaTeX project “P”')
    assert protocol.display_text('user', note) == 'Please fix it'
    context = protocol.agent_context(True, True)
    assert '"app": "latex"' in context and '"app": "slides"' in context and 'add_latex' in context
    assert protocol.agent_context(False, False) == ''


def test_assistant_context_mentions_the_editors(home):
    from spm_studio.documents import settings
    from spm_studio.ai.config import spm_context_file
    path = spm_context_file(home / 'work')
    assert 'presentation_templates' in path.read_text(encoding='utf8')
    assert '<spm-doc>' not in path.read_text(encoding='utf8')
    settings.update(latex_enabled=True, slides_enabled=True)
    text = spm_context_file(home / 'work').read_text(encoding='utf8')
    assert '<spm-doc>' in text and 'LaTeX editor' in text and 'latex_templates' in text


# ============================================================================= Overleaf
def test_overleaf_addresses():
    from spm_studio.documents import overleaf
    pid = '0123456789abcdef01234567'
    for text in (f'https://www.overleaf.com/project/{pid}', f'https://git.overleaf.com/{pid}', pid,
                 f'https://latex.uni.edu/project/{pid}?x=1'):
        assert overleaf.project_id_from_url(text) == pid
    with pytest.raises(overleaf.OverleafError):
        overleaf.project_id_from_url('https://www.overleaf.com/project')
    assert overleaf.git_url(pid, {}) == f'https://git.overleaf.com/{pid}'
    assert overleaf.git_url(pid, {'overleaf_server': 'https://latex.uni.edu/'}) == f'https://latex.uni.edu/git/{pid}'
    assert overleaf.project_page(pid, {}) == f'https://www.overleaf.com/project/{pid}'


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_overleaf_upload_clone_push_pull_with_a_local_git_server(home, tmp_path):
    from spm_studio.documents import overleaf
    pid = 'abcdefabcdefabcdefabcdef'
    server = tmp_path / 'server'
    server.mkdir()
    bare = server / pid
    subprocess.run(['git', 'init', '--bare', '-q', '-b', 'master', str(bare)], check=True)
    seed = tmp_path / 'seed'
    subprocess.run(['git', 'clone', '-q', str(bare), str(seed)], check=True, capture_output=True)
    (seed / 'main.tex').write_text('\\documentclass{article}\\begin{document}x\\end{document}\n')
    (seed / 'figures').mkdir()
    (seed / 'figures' / '.keep').write_text('')
    for args in (['add', '-A'], ['-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'init'],
                 ['push', '-q', 'origin', 'HEAD:master']):
        subprocess.run(['git', *args], cwd=seed, check=True, capture_output=True)
    conf = {'overleaf_git_url': server.as_uri()}
    client = overleaf.OverleafClient(conf, token='secret-token', cache=tmp_path / 'cache')
    assert client.test(pid) == 'Connected'
    assert 'figures' in client.folders(pid)
    figure = tmp_path / 'scan.pdf'
    figure.write_bytes(b'%PDF')
    assert client.upload(pid, [figure], 'figures/new') == ['figures/new/scan.pdf']
    log = subprocess.run(['git', '--git-dir', str(bare), 'log', '--name-only', '--format=%s'], capture_output=True,
                         text=True).stdout
    assert 'figures/new/scan.pdf' in log
    # editor working copy: clone, edit, push; edit on "Overleaf", pull
    work = tmp_path / 'work'
    client.clone_project(pid, work)
    assert overleaf.OverleafClient.linked_project(work) == pid
    assert 'secret-token' not in (work / '.git' / 'config').read_text()
    (work / 'main.tex').write_text('changed\n')
    (work / '.spm_build').mkdir()
    (work / '.spm_build' / 'main.log').write_text('ignored')
    assert client.push_project(work) == 'Pushed to Overleaf'
    files = subprocess.run(['git', '--git-dir', str(bare), 'ls-tree', '-r', '--name-only', 'master'],
                           capture_output=True, text=True).stdout
    assert 'main.tex' in files and '.spm_build' not in files
    subprocess.run(['git', 'pull', '-q', 'origin', 'master'], cwd=seed, check=True, capture_output=True)
    (seed / 'refs.bib').write_text('@misc{a,title={A}}\n')
    for args in (['add', '-A'], ['-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'bib'],
                 ['push', '-q', 'origin', 'HEAD:master']):
        subprocess.run(['git', *args], cwd=seed, check=True, capture_output=True)
    client.pull_project(work)
    assert (work / 'refs.bib').is_file()
    with pytest.raises(overleaf.OverleafError):
        client.upload(pid, [figure], '../outside')


# ============================================================================ GUI part
@pytest.fixture
def qt(home, monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    pytest.importorskip('PySide6')
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    monkeypatch.setenv('SPM_STUDIO_NO_UPDATE_CHECK', '1')
    app = QApplication.instance() or QApplication([])
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(home / 'config'))
    return app


@pytest.fixture
def window(qt, home):
    from spm_studio.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    qt.processEvents()
    yield win
    win.documents.close_all()
    win.close()
    qt.processEvents()


def _wait(app, condition, ms=15000):
    import time
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return condition()


def test_buttons_appear_only_when_switched_on_and_settings_page(window, qt):
    from spm_studio.documents import settings
    from spm_studio.ui.settings_dialog import SettingsDialog, PAGES
    assert not window.latex_button.isVisible() and not window.slides_button.isVisible()
    assert ('documents', 'Documents', 'latex') in PAGES
    dialog = SettingsDialog(window, 'documents')
    dialog.show()
    qt.processEvents()
    from PySide6.QtWidgets import QCheckBox
    dialog.findChild(QCheckBox, 'DocumentsLatexEnabledV008').setChecked(True)
    dialog.findChild(QCheckBox, 'DocumentsSlidesEnabledV008').setChecked(True)
    qt.processEvents()
    assert settings.load()['latex_enabled'] and window.latex_button.isVisible() and window.slides_button.isVisible()
    dialog.show_page('library')
    for kind in ('latex_templates', 'slide_templates'):
        dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData(kind))
        qt.processEvents()
        assert dialog.items.count() >= 4 and dialog.lib_new_template.isVisible()
    dialog.close()


def test_latex_editor_figures_assistant_and_compile(window, qt, home, tmp_path):
    from PySide6.QtGui import QImage, QColor
    from spm_studio.documents import latex_project, templates, tex, protocol
    project = latex_project.create_project(tmp_path, 'Paper', templates.find('latex', 'Article').path)
    win = window.documents.open_latex(project)
    qt.processEvents()
    assert win.current and win.current.endswith('main.tex') and win.windowTitle().startswith('Paper')
    assert win.auto_button.objectName() == 'LatexAutoCompileV008'
    win.auto_button.setChecked(False)
    # an SVG figure becomes a vector PDF in figures/ and is included at the cursor
    svg = tmp_path / 'scan_topo.svg'
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><rect width="200" '
                   'height="100" fill="red"/></svg>')
    cursor = win.editor.textCursor()
    cursor.setPosition(win.editor.toPlainText().index('Conclude.'))
    win.editor.setTextCursor(cursor)
    rel = win.insert_figure([svg], 'Topography')
    assert rel == 'figures/scan_topo.pdf' and (project / rel).read_bytes().startswith(b'%PDF')
    assert '\\includegraphics[width=0.8\\linewidth]{figures/scan_topo.pdf}' in win.editor.toPlainText()
    win.editor.undo()
    assert 'scan_topo' not in win.editor.toPlainText()
    win.editor.redo()
    # the assistant's actions, through the hub
    hub = window.documents
    win.activateWindow()
    hub.note_active(win)
    requests = protocol.parse_requests(
        '<spm-doc>{"app": "latex", "action": "read"}</spm-doc>'
        '<spm-doc>{"app": "latex", "action": "replace", "find": "Conclude.", "replace": "We conclude."}</spm-doc>'
        '<spm-doc>{"app": "latex", "action": "write_file", "path": "sections/extra.tex", "text": "\\\\section{X}"}</spm-doc>'
        '<spm-doc>{"app": "latex", "action": "write_file", "path": "../../escape.tex", "text": "x"}</spm-doc>'
        '<spm-doc>{"app": "latex", "action": "insert", "text": "\\\\input{sections/extra}", "at": "end"}</spm-doc>')
    results = hub.ai_execute(requests)
    assert 'Content of the open file' in results[0][1] and 'figures/scan_topo.pdf' in results[0][1]
    assert results[1][1].startswith('Replaced') and results[3][1].startswith('ERROR')
    assert (project / 'sections' / 'extra.tex').read_text() == '\\section{X}'
    assert not (tmp_path.parent / 'escape.tex').exists()
    win.open_file(str(project / 'main.tex'))
    assert 'We conclude.' in win.editor.toPlainText()
    assert win.editor.toPlainText().index('\\input{sections/extra}') < win.editor.toPlainText().index('\\end{document}')
    assert 'LaTeX project' in win.ai_state()
    assert win.save_all() and 'We conclude.' in (project / 'main.tex').read_text()
    # outline and completion
    assert win.outline.topLevelItemCount() >= 4
    assert 'binnig1982' in win._completions('cite') and 'sections/extra' in win._completions('file')
    if _tex_available():
        win.insert_figure([svg])        # keep a valid figure for the compile
        assert win.compile_and_wait(240000), win._last_log[-2000:]
        assert win.pdf.pdf_path and Path(win.pdf.pdf_path).is_file()
        if win.pdf.document is not None:
            assert _wait(qt, lambda: win.pdf.page_count() >= 1)
        # a broken document reports the error with its line
        win.ai_insert('\\undefinedcommandxyz', 'line:30')
        win.compile_and_wait(240000)
        assert win.summary.errors and any(e.line for e in win.summary.errors)
    win.close()
    qt.processEvents()


def test_presentation_editor_items_undo_save_export(window, qt, home, tmp_path):
    from PySide6.QtGui import QImage, QColor
    from spm_studio.documents import deck, templates, protocol
    file = deck.create_project(tmp_path, 'Talk', template=templates.load_slides_template('Scientific_Talk'))
    win = window.documents.open_slides(file)
    qt.processEvents()
    assert win.thumbs.count() == 5 and win.present_button.objectName() == 'SlidesPresentV008'
    png = tmp_path / 'scan.png'
    image = QImage(300, 150, QImage.Format.Format_RGB32)
    image.fill(QColor('#3366aa'))
    image.save(str(png))
    win.add_figure([png], new_slide=True, title='Topography')
    assert win.thumbs.count() == 6 and win.index == 1 + 0 or win.index >= 1
    items = win.current_slide()['items']
    assert items[0]['role'] == 'title' and 'Topography' in deck.plain_text(items[0]['html'])
    picture = items[-1]
    assert picture['type'] == 'image' and (file.parent / picture['src']).is_file()
    assert abs(picture['w'] / picture['h'] - 2.0) < 0.01
    text = win.add_text('Hello', x=48, y=300, w=400, h=40)
    shape = win.add_shape('arrow')
    latex = win.add_latex(r'$\alpha + \beta$', x=48, y=400, w=300, h=50)
    count = len(win.current_slide()['items'])
    win.undo_action()
    assert len(win.current_slide()['items']) == count - 1
    win.redo_action()
    assert len(win.current_slide()['items']) == count
    # move and select
    item = win.scene.graphics[text['id']]
    item.setSelected(True)
    win.nudge(10, 0)
    win.commit()
    assert win.current_slide()['items'][-3]['x'] == 58
    win.delete_selected()
    assert all(i['id'] != text['id'] for i in win.current_slide()['items'])
    # slides
    win.new_slide('section', title='Part 2')
    win.duplicate_slide()
    n = len(win.slides())
    win.delete_slide()
    assert len(win.slides()) == n - 1
    # assistant actions
    window.documents.note_active(win)
    reqs = protocol.parse_requests(
        '<spm-doc>{"app": "slides", "action": "add_slide", "layout": "title_content", "title": "Summary", '
        '"body": "• one\\n• two", "notes": "say it"}</spm-doc>'
        '<spm-doc>{"app": "slides", "action": "add_latex", "slide": "current", "source": "$E=mc^2$"}</spm-doc>'
        '<spm-doc>{"app": "slides", "action": "read"}</spm-doc>'
        '<spm-doc>{"app": "slides", "action": "go_to", "slide": 99}</spm-doc>')
    results = window.documents.ai_execute(reqs)
    assert results[0][1].startswith('Added slide') and win.current_slide()['notes'] == 'say it'
    outline = json.loads(results[2][1])
    assert outline['slides'][win.index]['text'][0] == 'Summary' and results[3][1].startswith('ERROR')
    title_id = win.current_slide()['items'][0]['id']
    window.documents.ai_execute([{'app': 'slides', 'action': 'update_item', 'item': title_id, 'text': 'Conclusions'}])
    assert 'Conclusions' in deck.plain_text(win.current_slide()['items'][0]['html'])
    # save, reload, export
    assert win.save()
    again = deck.load(file)
    assert again['slides'][win.index]['notes'] == 'say it' and len(again['slides']) == len(win.slides())
    pdf = win.export_pdf(tmp_path / 'talk.pdf')
    assert pdf.read_bytes().startswith(b'%PDF')
    from spm_studio.documents.ui.slide_items import render_slide
    thumb = render_slide(win.deck, 0, file.parent, 320, win.renderer)
    assert thumb.width() == 320 and thumb.height() == 180
    try:
        import pptx  # noqa: F401
        out = win.export_pptx(tmp_path / 'talk.pptx')
        assert out is not None and zipfile.ZipFile(out).namelist()
        from spm_studio.documents.ui.pptx_io import import_pptx
        imported = import_pptx(out, tmp_path / 'imported')
        assert len(deck.load(imported)['slides']) == len([s for s in win.slides()])
    except ImportError:
        pass
    win.present(0)
    qt.processEvents()
    win._slideshow.next()
    win._slideshow.close()
    win.close()
    qt.processEvents()


def test_export_destinations_deliver_to_open_editors(window, qt, home, tmp_path):
    from PySide6.QtGui import QImage, QColor
    from spm_studio.documents import latex_project, deck, settings
    settings.update(latex_enabled=True, slides_enabled=True)
    project = latex_project.create_project(tmp_path, 'Doc')
    latex = window.documents.open_latex(project)
    latex.auto_button.setChecked(False)
    slides = window.documents.open_slides(deck.create_project(tmp_path, 'Deck'))
    png = tmp_path / 'fig.png'
    image = QImage(100, 100, QImage.Format.Format_RGB32)
    image.fill(QColor('#ffffff'))
    image.save(str(png))
    notes = window.documents.deliver([png, Path(str(png) + '.provenance.json')],
                                     {'latex': latex, 'slides': slides, 'slides_mode': 'current'}, caption='A figure')
    assert len(notes) == 2
    assert '{figures/fig.png}' in latex.editor.toPlainText() and '\\caption{A figure}' in latex.editor.toPlainText()
    assert slides.current_slide()['items'][-1]['src'] == 'media/fig.png'
    from spm_studio.documents.ui.send_dialog import SendDialog
    dialog = SendDialog(window.documents, window, preset={'latex': latex, 'folder': False})
    targets = dialog.targets()
    assert targets['folder'] is False and targets['latex'] is latex
    dialog.close()
    for win in (latex, slides):
        win.close()
    qt.processEvents()


def test_formula_renderer_renders_or_reports(qt, home):
    from spm_studio.documents.ui.formula import FormulaRenderer
    renderer = FormulaRenderer()
    result = renderer.render_blocking(r'$\int_0^1 x\,\mathrm{d}x$', '#112233', 200, 'center', '', timeout=60000)
    key = renderer.request(r'$\int_0^1 x\,\mathrm{d}x$', '#112233', 200, 'center', '')
    assert result is not None or renderer.error(key)
    if result is not None:
        image, w, h = result
        assert not image.isNull() and w > 0 and h > 0
    bad = renderer.render_blocking(r'\begin{nonsense}', '#000000', 200, 'center', '', timeout=60000)
    assert bad is None or bad[0] is not None
