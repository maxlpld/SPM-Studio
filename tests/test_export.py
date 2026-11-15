from pathlib import Path
import numpy as np
from spm_studio.core.export import unique_target,provenance
from spm_studio.core.models import Geometry,Channel,Scan,ImageStyle

def test_collision_safe_and_source_fingerprint(tmp_path):
    x=tmp_path/'x.sxm';x.write_bytes(b'example')
    g=Geometry((2,2),(1e-9,1e-9))
    scan=Scan(x,{'Z':Channel('Z','m',{'forward':np.zeros((2,2))},g)})
    p=provenance(scan,'Z','forward',[],ImageStyle(),{'schema_version':1})
    assert p['fingerprint']['size_bytes']==7
    out=tmp_path/'fig.png';out.touch()
    assert unique_target(out)==tmp_path/'fig_001.png'
