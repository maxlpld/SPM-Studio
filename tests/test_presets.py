import pytest
from spm_studio.core.presets import validate_profile,validate_theme,validate_export,write_json,read_json

def test_roundtrip_and_bad_theme(tmp_path):
    profile={'schema_version':1,'name':'test','style':{'colormap':'gray','low':1,'high':99},
             'processing':[{'operation':'plane','params':{},'enabled':True}]}
    p=tmp_path/'profile.json'
    write_json(p,profile,validate_profile)
    obj=read_json(p,validate_profile)
    assert obj['processing'][0]['operation']=='plane'
    assert obj['style']['gamma']==1.0
    with pytest.raises(ValueError):validate_theme({'schema_version':1,'accent':'red'})
    assert validate_export({'schema_version':1})['dpi']==1200   # v32: max quality by default
    with pytest.raises(ValueError):validate_export({'schema_version':1,'width_mm':-1})
