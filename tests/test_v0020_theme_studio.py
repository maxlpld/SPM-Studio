"""Theme Studio (v0.0.20, from the private beta): roles, profiles, stylesheet, SVG templates, strict package import, theme packages."""
import json
import re
import zipfile
from pathlib import Path

import pytest

TOKENS = {'background': '#121417', 'surface': '#1A1D22', 'raised': '#22262B', 'sidebar': '#16191D',
          'input': '#16181C', 'foreground': '#E6E8EC', 'muted': '#99A1AE', 'subtle': '#6B7280', 'border': '#2E3238',
          'border_strong': '#40454D', 'hover': '#272B31', 'pressed': '#30353C', 'accent': '#3FB8A6',
          'accent_hover': '#5CC4B4', 'accent_fg': '#0B0D10', 'accent_soft': '#1F3B38', 'selection': '#1F3B38',
          'danger': '#F07070', 'success': '#4CC38A', 'warning': '#E8B54D', 'font_family': '', 'font_size': 10.0,
          'radius': 6}


def test_profile_roles_cascade_and_stylesheet():
    from spm_studio.theme_studio import model
    p = model.new_profile('Lab dark', TOKENS, 'graphite')
    model.set_prop(p, 'button', 'normal', 'background', '#3366FF80')           # 50 % alpha background
    model.set_prop(p, 'button', 'hover', 'color', '#FFFFFF')
    model.set_prop(p, 'button.primary', 'normal', 'radius', 14)
    model.set_prop(p, 'log', 'normal', 'font_family', 'DejaVu Sans Mono')
    model.set_prop(p, 'progress.fill', 'normal', 'background', '#FF8800')
    qss = model.role_qss(p)
    assert 'QPushButton { background: rgba(51, 102, 255, 128); }' in qss
    assert 'QPushButton:hover { color: #FFFFFF; }' in qss
    assert 'QPushButton[primary="true"], QToolButton[primary="true"] { border-radius: 14px; }' in qss
    assert qss.index('QPushButton {') < qss.index('QPushButton[primary="true"]')   # general before specific
    assert 'QProgressBar::chunk { background: #FF8800; }' in qss
    assert 'QPlainTextEdit[readOnly="true"]' in qss
    scoped = model.role_qss(p, '#ThemePreview')
    assert '#ThemePreview QPushButton {' in scoped
    with pytest.raises(ValueError):
        model.set_prop(p, 'progress.fill', 'normal', 'font_size', 12)           # unsupported → explained
    with pytest.raises(ValueError):
        model.set_prop(p, 'button', 'normal', 'background', 'red')
    model.set_prop(p, 'button', 'hover', 'color', None)
    assert 'hover' not in p['roles']['button']
    again = model.validate_profile(json.loads(json.dumps(p)))
    assert again['roles'] == p['roles'] and again['base']['accent'] == '#3FB8A6'


def test_contrast_safeguard():
    from spm_studio.theme_studio import model
    p = model.new_profile('x', TOKENS)
    assert model.contrast_warnings(p, TOKENS) == []
    model.set_prop(p, 'button.primary', 'normal', 'background', '#0B0D10')     # same as its text
    warnings = model.contrast_warnings(p, TOKENS)
    assert warnings and 'Primary buttons' in warnings[0]
    assert round(model.contrast('#FFFFFF', '#000000')) == 21


def test_profile_validation_rejects_bad_data():
    from spm_studio.theme_studio import model
    with pytest.raises(ValueError):
        model.validate_profile({'schema': 2})
    bad = model.new_profile('x', TOKENS)
    bad['base']['font_size'] = 99
    with pytest.raises(ValueError):
        model.validate_profile(bad)
    odd = model.new_profile('x', TOKENS)
    odd['roles'] = {'nonexistent': {'normal': {'color': '#FFFFFF'}}, 'button': {'normal': {'evil': 'x'}}}
    assert model.validate_profile(odd)['roles'] == {}                           # unknown data dropped


def test_template_reflects_theme_and_is_complete(tmp_path):
    from spm_studio.theme_studio import model, svgskin
    p = model.new_profile('Mine', TOKENS)
    model.set_prop(p, 'button', 'normal', 'background', '#AA2244')
    model.set_prop(p, 'button', 'normal', 'radius', 12)
    pkg = svgskin.export_template(tmp_path / 'template.zip', 'Mine', p, TOKENS)
    with zipfile.ZipFile(pkg) as zf:
        names = set(zf.namelist())
        button = zf.read('svg/button/normal.svg').decode()
        readme = zf.read('README.md').decode()
        manifest = json.loads(zf.read('manifest.json'))
    assert set(svgskin.required_files()) <= names and set(svgskin.optional_files()) <= names
    assert 'fill="#AA2244"' in button and 'rx="12"' in button and 'viewBox="0 0 120 32"' in button
    assert 'Exact file names are required' in readme and 'svg/progress.fill/normal.svg' in readme
    assert manifest['roles']['button']['insets'] == [10, 10, 10, 10]
    for name in names:
        if name.endswith('.svg'):
            with zipfile.ZipFile(pkg) as zf:
                assert svgskin.check_svg(zf.read(name), name) == []
    manifest, svgs = svgskin.validate_package(pkg)                              # its own export imports cleanly
    assert len(svgs) == len(svgskin.required_files()) + len(svgskin.optional_files())


def _edit(pkg: Path, out: Path, changes: dict, remove=()):
    with zipfile.ZipFile(pkg) as src, zipfile.ZipFile(out, 'w') as dst:
        for name in src.namelist():
            if name in remove:
                continue
            dst.writestr(name, changes.pop(name, src.read(name)))
        for name, data in changes.items():
            dst.writestr(name, data)
    return out


def test_edited_complete_package_installs_and_changes_the_stylesheet(tmp_path):
    from spm_studio.theme_studio import model, svgskin
    pkg = svgskin.export_template(tmp_path / 't.zip', 'Mine', model.new_profile('m', TOKENS), TOKENS)
    star = ('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="32" viewBox="0 0 120 32">'
            '<path d="M10 1 H110 L119 16 L110 31 H10 L1 16 Z" fill="#FF00AA"/></svg>')
    edited = _edit(pkg, tmp_path / 'e.zip', {'svg/button/normal.svg': star})
    manifest, svgs = svgskin.validate_package(edited)
    folder = svgskin.install(manifest, svgs, tmp_path / 'skins')
    assert 'L119 16' in (folder / 'svg/button/normal.svg').read_text()
    qss = svgskin.skin_qss(folder, manifest)
    assert re.search(r'QPushButton \{ border-image: url\("[^"]+button/normal\.svg"\) 10 10 10 10 stretch stretch', qss)
    assert 'QProgressBar::chunk { border-image' in qss and 'QPushButton[flat="true"]' in qss
    assert svgskin.installed_skins(tmp_path / 'skins')[folder.name]['name'] == 'Mine'


@pytest.mark.parametrize('case', ['missing', 'renamed', 'corrupt', 'script', 'external', 'doctype', 'event',
                                  'badmanifest', 'traversal', 'unknown', 'noviewbox'])
def test_invalid_packages_are_refused_with_a_precise_report(tmp_path, case):
    from spm_studio.theme_studio import model, svgskin
    pkg = svgskin.export_template(tmp_path / 't.zip', 'Mine', model.new_profile('m', TOKENS), TOKENS)
    svg = lambda body: f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 32">{body}</svg>'
    target = 'svg/button/hover.svg'
    variants = {
        'missing': ({}, [target], 'Missing required file svg/button/hover.svg'),
        'renamed': ({'svg/button/Hover.svg': svg('')}, [target], 'names are case-sensitive'),
        'corrupt': ({target: '<svg xmlns="http://www.w3.org/2000/svg"'}, [], 'not valid XML'),
        'script': ({target: svg('<script>alert(1)</script>')}, [], '<script> not allowed'),
        'external': ({target: svg('<image href="https://evil.example/x.png" width="5" height="5"/>')}, [],
                     'not allowed'),
        'doctype': ({target: '<!DOCTYPE svg [<!ENTITY x "y">]>' + svg('')}, [], 'DOCTYPE not allowed'),
        'event': ({target: svg('<rect width="5" height="5" onclick="x()"/>')}, [], 'event attribute'),
        'badmanifest': ({'manifest.json': '{"schema": 7}'}, [], 'not an SPM Studio SVG skin manifest'),
        'traversal': ({'../evil.svg': svg('')}, [], 'Unsafe path'),
        'unknown': ({'svg/button/huge.svg': svg('')}, [], 'Unknown file svg/button/huge.svg'),
        'noviewbox': ({target: '<svg xmlns="http://www.w3.org/2000/svg"/>'}, [], 'viewBox'),
    }
    changes, remove, expected = variants[case]
    bad = _edit(pkg, tmp_path / 'bad.zip', dict(changes), remove)
    with pytest.raises(svgskin.SkinError) as err:
        svgskin.validate_package(bad)
    assert expected in str(err.value)
    assert not (tmp_path / 'skins').exists()                                   # nothing installed


def test_demo_skin_changes_shapes_not_only_colours(tmp_path):
    from spm_studio.theme_studio import svgskin
    pkg = svgskin.demo_package(tmp_path / 'demo.zip', TOKENS)
    manifest, svgs = svgskin.validate_package(pkg)
    button = svgs['svg/button/normal.svg'].decode()
    assert '<path d="M10 1 H110 L119 10' in button and 'pattern' in button        # chamfer + stripes
    assert 'patternTransform="skewX(-30)"' in svgs['svg/progress.fill/normal.svg'].decode()
    assert 'M1 14 V1 H14' in svgs['svg/panel/normal.svg'].decode()                 # corner brackets


def test_theme_packages_round_trip_and_migration(tmp_path):
    from spm_studio.theme_studio import model, store as store_mod, svgskin
    first = store_mod.Store(tmp_path / 'a')
    p = model.new_profile('Lab dark', TOKENS)
    model.set_prop(p, 'button', 'normal', 'background', '#123456')
    manifest, svgs = svgskin.validate_package(svgskin.demo_package(tmp_path / 'demo.zip', TOKENS))
    p['skin'] = svgskin.install(manifest, svgs, first.skins_dir).name
    slug = first.save(p)
    with pytest.raises(FileExistsError):
        first.save(p, slug, overwrite=False)                                     # Save As never overwrites
    pkg = first.export_package(slug, tmp_path / 'lab.zip')
    second = store_mod.Store(tmp_path / 'b')                                     # another installation
    new_slug, notes = second.import_package(pkg)
    got = second.load(new_slug)
    assert got['roles'] == p['roles'] and got['skin'] and (second.skins_dir / got['skin'] / 'manifest.json').is_file()
    assert any('SVG skin' in n for n in notes)
    plain = tmp_path / 'old_theme.json'
    plain.write_text(json.dumps({'schema_version': 1, 'background': '#000000', 'accent': '#FF0000'}))
    migrated, notes = second.import_package(plain)
    assert second.load(migrated)['base']['accent'] == '#FF0000' and 'converted' in notes[0]
    copy = second.duplicate(new_slug, 'Lab dark copy')
    renamed = second.rename(copy, 'Bench')
    assert second.load(renamed)['name'] == 'Bench' and copy not in second.list()
    second.delete(renamed)
    assert renamed not in second.list()
    assert store_mod.theme_json(got)['schema_version'] == 1
