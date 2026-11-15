"""Regression against the archived MultiFrame science and original CPD legend fields."""
from __future__ import annotations
import importlib.util
import json
import sys
import zipfile
from pathlib import Path
import numpy as np

import pytest

ROOT = Path(__file__).resolve().parents[1]
# Upstream reference archive used on the original development machine; it is not part of the repository.
LEGACY_MULTIFRAME = ROOT/'legacy_reference/spm-multiframe-v0.1.2.zip'
needs_legacy_archive = pytest.mark.skipif(not LEGACY_MULTIFRAME.is_file(),
    reason='developer-only reference archive legacy_reference/spm-multiframe-v0.1.2.zip is not shipped')


@needs_legacy_archive
def test_original_engine_files_shipped_and_unmodified():
    archive=ROOT/'legacy_reference/spm-multiframe-v0.1.2.zip'
    with zipfile.ZipFile(archive) as z:
        for name in ('lattice_measurements','multiframe_drift_stack'):
            vendor=ROOT/'scripts'/name/'vendor/spm_multiframe'
            for path in ('analysis/lattice.py','analysis/drift.py','stacking/stack_pipeline.py',
                         'geometry/coordinates.py','geometry/overlap.py'):
                original=next(n for n in z.namelist() if n.endswith('src/spm_multiframe/'+path))
                assert (vendor/path).read_bytes()==z.read(original)


def test_legend_restores_original_fit_fields():
    p=ROOT/'scripts/cpd_histogram/module.py'
    spec=importlib.util.spec_from_file_location('cpd_full_legend',p)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rng=np.random.default_rng(8)
    low=rng.normal(.22,.012,2500)
    high=rng.normal(.44,.018,2700)
    fit={}
    masks=[]
    for name,c,values in [('Terrace','#ff8811',low),('Island','#0088cc',high)]:
        _,_,parts,quality=mod._fit_populations(values,1,100,with_quality=True)
        mu,sigma,amp=parts[0]
        ae,me,se=quality['errors'].get(mu,(float('nan'),)*3)
        fit[name]={'n':len(values),'requested':1,'r_squared':quality['r_squared'],
                   'components':[{'mu':mu,'mu_error':me,'sigma':sigma,
                        'sigma_error':se,'amplitude':amp,'amplitude_error':ae}]}
        masks.append({'name':name,'color':c})
    details=mod._mask_legend_details(masks,fit,len(low)+len(high),1000,'mV')
    assert len(details)==2
    for _,_,text in details:
        for field in ('histogram','pixels','Gaussian','A =','x_max','μ','σ','R²'):
            assert field in text
    diffs=mod._peak_difference_rows(masks,fit)
    assert len(diffs)==1
    assert abs(diffs[0][2]-.22)<.015
    assert not mod._peak_difference_rows(masks,fit,which='none')
    assert all(np.isfinite(x['components'][0]['mu']) for x in fit.values())


@needs_legacy_archive
def test_original_engine_studio_selected_source_and_stack(tmp_path):
    # Reuse the *original* upstream deterministic SXM generator directly from
    # the archived source. Neither the science generator nor core math is edited.
    archive=ROOT/'legacy_reference/spm-multiframe-v0.1.2.zip'
    engine=ROOT/'scripts/multiframe_drift_stack'
    sys.path.insert(0,str(engine/'vendor'))
    with zipfile.ZipFile(archive) as z:
        name=next(n for n in z.namelist() if n.endswith('examples/generate_synthetic_dataset.py'))
        code=compile(z.read(name),name,'exec')
    scope={'__name__':'test_fixture'}
    exec(code,scope)
    data=tmp_path/'input'
    scope['build_dataset'](data)
    files=sorted(data.glob('*.sxm'))
    assert len(files)==4
    # An extra SXM in the folder must NOT be processed when unselected.
    (data/'extra_unselected.sxm').write_bytes(files[0].read_bytes())
    sys.path.insert(0,str(engine))
    from legacy_engine import run_original
    class Context:
        scan_path=files[0]
        source_paths=files[1:]
        channel='Z'
        output_dir=tmp_path/'output'
        def log(self,*args,**kwargs):pass
        def progress(self,*args,**kwargs):pass
        def result_file(self,*args,**kwargs):pass
    ctx=Context()
    ctx.output_dir.mkdir()
    output=run_original(ctx,estimate_drift=True,stack=True,
                        drift_bootstrap=0,lattice_bootstrap=0,
                        stack_channels=['Z','Bias'],method='mean')
    analysis=json.loads((ctx.output_dir/'multiframe_analysis/drift_lattice_results.json').read_text())
    assert len(analysis['source_files'])==4
    assert analysis['lattice']['a_nm']==__import__('pytest').approx(.94,abs=.12)
    assert analysis['lattice']['b_nm']==__import__('pytest').approx(.77,abs=.12)
    assert analysis['lattice']['gamma_deg']==__import__('pytest').approx(67,abs=8)
    final=json.loads(output.manifest_path.read_text())
    assert 'Z' in str(final) and 'Bias' in str(final)
    assert output.report_path.exists()


def test_safe_upgrade_keeps_custom_scripts_and_removals(monkeypatch,tmp_path):
    from spm_studio.core import paths
    monkeypatch.setenv('XDG_DATA_HOME',str(tmp_path/'data'))
    scripts=paths.scripts_dir()
    if LEGACY_MULTIFRAME.is_file():
        with zipfile.ZipFile(LEGACY_MULTIFRAME) as z:
            assert any(x.endswith('/analysis/lattice.py') for x in z.namelist())
    # Simulate an existing v0.4.3 user Scripts folder.
    previous=ROOT/'scripts/factory_v043_hashes.json'
    hashes=json.loads(previous.read_text())
    archive=ROOT/'legacy_reference'  # Original studio archive not bundled; use known hashes.
    import subprocess
    # Restore one old module body from its archived root project via stored snapshot,
    # available during this patch's testing run.
    old_zip=ROOT/'legacy_reference/spm-modular-studio-v0.4.3.zip'   # developer-only, not shipped
    if not old_zip.is_file():
        __import__('pytest').skip('Full previous studio ZIP is not supplied')
    with zipfile.ZipFile(old_zip) as z:
        for name in ('cpd_histogram','lattice_measurements','multiframe_drift_stack'):
            (scripts/name).mkdir(parents=True)
            for f in ('module.json','module.py'):
                original=z.read(f'spm-modular-studio/scripts/{name}/{f}')
                assert __import__('hashlib').sha256(original).hexdigest()==hashes[name][f]
                (scripts/name/f).write_bytes(original)
    (scripts/'cpd_histogram/module.py').write_text('# Personal implementation; do not overwrite\n')
    (scripts/'lattice_measurements/module.json').unlink()
    notes=paths.upgrade_factory_modules_v050()
    assert (scripts/'cpd_histogram/module.py').read_text().startswith('# Personal implementation')
    assert json.loads((scripts/'cpd_histogram/module.json').read_text())['version']=='0.5.0'
    assert not (scripts/'lattice_measurements/module.json').exists()
    assert (scripts/'multiframe_drift_stack/vendor/spm_multiframe/analysis/lattice.py').exists()
    assert (scripts/'.factory_backups_v050/multiframe_drift_stack/module.py').exists()
    assert paths.upgrade_factory_modules_v050()==[]


def test_original_modules_use_importable_dependency_names():
    from spm_studio.core.registry import load_manifest
    for name in ('multiframe_drift_stack','lattice_measurements'):
        manifest=load_manifest(ROOT/'scripts'/name/'module.json')
        assert 'skimage' in manifest.requires
        assert 'scikit-image' not in manifest.requires
        assert manifest.entrypoint=='module:run'
