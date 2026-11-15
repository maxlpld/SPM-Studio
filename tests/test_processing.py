import numpy as np
import pytest
from spm_studio.core.models import ProcessingStep
from spm_studio.core.processing import apply

def test_known_plane_with_nan_without_mutating_source():
    y,x=np.indices((60,90))
    a=2e-9+1e-10*x+2e-10*y
    a=a.astype(float);a[5,8]=np.nan
    untouched=a.copy()
    z=apply(a,[ProcessingStep('plane')])
    assert np.nanmax(np.abs(z))<1e-21
    assert np.isnan(z[5,8]);np.testing.assert_allclose(a,untouched,equal_nan=True)

def test_processing_order_and_inverse():
    a=np.array([[1.,2.,3.],[3,4,5]])
    b=apply(a,[ProcessingStep('row_median'),ProcessingStep('invert')])
    c=apply(a,[ProcessingStep('invert'),ProcessingStep('row_median')])
    assert b.shape==a.shape and c.shape==a.shape
    np.testing.assert_allclose(apply(a,[ProcessingStep('invert')]),-a)
    np.testing.assert_allclose(apply(a,[ProcessingStep('invert',enabled=False)]),a)

def test_line_poly_does_not_change_source():
    y,x=np.indices((20,30))
    a=x**2+3*x+10 + np.sin(y)
    result=apply(a,[ProcessingStep('line_poly',{'degree':2})])
    assert np.nanmax(np.nanstd(result,axis=1))<1e-10
    assert a[1,10]!=result[1,10]

def test_invalid_operation_is_error():
    with pytest.raises(ValueError):apply(np.ones((3,3)),[ProcessingStep('surprise')])
