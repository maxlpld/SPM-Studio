"""ROI-only primitive lattice calculation using original MultiFrame 0.1.2 routines."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np


def solve_roi(crop,roi_geometry):
    vendor=Path(__file__).resolve().parent/'vendor'
    if str(vendor) not in sys.path:sys.path.insert(0,str(vendor))
    from spm_multiframe.analysis.fft import compute_fft,detect_fft_peaks
    from spm_multiframe.analysis.lattice import lattice_candidates_from_fft,reduce_direct_basis,lattice_parameters
    from spm_multiframe.config import AnalysisConfig
    from spm_multiframe.models import GridDefinition
    nx=crop.shape[1];ny=crop.shape[0]
    dx,dy=roi_geometry['pixel_size_nm']
    # FFT sees positive array rows downward. Its y-frequency and direct y
    # are therefore reflected into the Studio +y-up local convention.
    grid=GridDefinition(np.arange(nx,dtype=float)*dx,np.arange(ny,dtype=float)*dy)
    config=AnalysisConfig()
    fft=compute_fft(crop,grid)
    peaks=detect_fft_peaks(fft,dc_radius_bins=config.fft_dc_radius_bins,
                           min_peak_distance_bins=config.fft_min_peak_distance_bins,
                           max_peaks=config.fft_max_peaks)
    candidates=lattice_candidates_from_fft(fft,peaks,config)
    if not candidates:
        raise ValueError('No reliable primitive lattice in this ROI. Enlarge the region or check lattice contrast; no values were invented.')
    best=candidates[0]
    basis=reduce_direct_basis(np.diag([1.,-1.])@best.direct_basis_nm)
    a,b,gamma=lattice_parameters(basis)
    return {'basis_local_nm':basis.tolist(),'a_nm':a,'b_nm':b,'gamma_deg':gamma,
            'score':float(best.score),'explained_fraction':float(best.explained_fraction),
            'peak_count':len(peaks), 'candidate_count':len(candidates),
            'method':'MultiFrame 0.1.2 FFT peak selection and Gauss-reduced primitive basis, ROI-only; no drift fit'}
