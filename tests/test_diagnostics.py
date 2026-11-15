from spm_studio.core.diagnostics import main
from test_reader_binary import create_sxm

def test_cli_reader_check(tmp_path,capsys):
    p=create_sxm(tmp_path/'ok.sxm')
    assert main([str(p)]) == 0
    text=capsys.readouterr().out
    assert 'Z [m] forward' in text
    assert 'Bias [V] forward' in text


def test_cli_nonzero_for_bad_file(tmp_path):
    p=tmp_path/'bad.gwy';p.write_bytes(b'bad')
    assert main([str(p)]) == 1
