"""Regression checks for the large multi-channel loading/OOM problem in 0.3.1.

A sparse SXM contains enough image bytes for many full-size channels, but no
large matrices have to be constructed to create the test fixture.
"""
import numpy as np
from spm_studio.core.io import read_scan
from spm_studio.core.display import preview_bounds, render_rgb
from spm_studio.core.models import ImageStyle
from spm_studio.core.processing import apply


def create_large_sparse_sxm(path, nx=1024, ny=1024, channels=16):
    rows=['Channel\tName\tUnit\tDirection\tCalibration\tOffset']
    for j in range(channels):
        rows.append(f'{j}\tC{j}\tm\tboth\t1\t0')
    hdr='\r\n'.join([':SCAN_PIXELS:',f'{nx} {ny}',':SCAN_RANGE:',
        '3e-8 3e-8',':SCAN_DIR:','up',':SCANIT_TYPE:','FLOAT MSBFIRST',
        ':DATA_INFO:',*rows,':SCANIT_END:'])+'\r\n'
    with path.open('wb') as f:
        f.write(hdr.encode('latin-1')+b'\x1a\x04')
        f.truncate(f.tell()+channels*2*nx*ny*4)
    return path


def test_many_channels_open_read_only_without_materialization(tmp_path):
    p=create_large_sparse_sxm(tmp_path/'large.sxm')
    scan=read_scan(p)
    assert len(scan.channels)==16
    for ch in scan.channels.values():
        for array in ch.traces.values():
            assert array.shape==(1024,1024)
            assert array.dtype==np.dtype('>f4')
            assert not array.flags.writeable
            assert not array.flags.owndata
            assert isinstance(array.base, np.memmap)
    assert scan.channels['C0'].get('forward')[0,0]==0


def test_first_preview_does_not_change_source(tmp_path):
    p=create_large_sparse_sxm(tmp_path/'preview.sxm',nx=512,ny=256,channels=2)
    raw=read_scan(p).channels['C0'].get('forward')
    style=ImageStyle()
    before=raw[0,0]
    processed=raw   # no active steps: must not duplicate or modify full image
    assert processed is raw
    bnd=preview_bounds(processed,style)
    rendered=render_rgb(processed,style,bnd,max_dimension=128)
    assert rendered.shape[1]<=128 and rendered.shape[0]<=128
    assert raw[0,0]==before
    assert not raw.flags.writeable


def test_sampled_preview_bounds_ignore_nans():
    arr=np.linspace(0,99,10_000,dtype='f4').reshape(100,100)
    arr[0,0]=np.nan
    bnd=preview_bounds(arr,ImageStyle(),max_samples=400)
    assert np.isfinite(bnd).all()
    assert bnd[0]<bnd[1]
