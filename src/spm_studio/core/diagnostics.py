"""Headless file-reader check for troubleshooting on the user's real scans."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import numpy as np
from .io import read_scan


def diagnose(path: Path) -> dict:
    scan = read_scan(path)
    data = {
        'source':str(scan.path),
        'reader':scan.metadata.get('reader'),
        'format':scan.metadata.get('format'),
        'warnings':scan.warnings,
        'channels':[],
    }
    for name,ch in scan.channels.items():
        traces=[]
        for direction,array in ch.traces.items():
            # Diagnostic counting is sampled: forcing all channels of a
            # disk-backed SXM into RAM would defeat fast opening.
            stride=max(1,int(np.ceil(np.sqrt(array.size/200_000))))
            sample=array[::stride,::stride]
            valid=int(np.count_nonzero(np.isfinite(sample)))
            traces.append({'trace':direction,'shape':list(array.shape),
                          'dtype':str(array.dtype), 'sampled_pixels':sample.size,
                          'sampled_finite':valid,'sampled_masked':int(sample.size-valid)})
        data['channels'].append({'name':name,'unit':ch.unit,'geometry':ch.geometry.to_dict(),
                                 'traces':traces})
    return data


def main(argv=None):
    parser=argparse.ArgumentParser(description='Validate SXM/GWY loading without opening the GUI')
    parser.add_argument('scans',nargs='+',help='Paths to .sxm/.gwy files')
    parser.add_argument('--json',action='store_true',help='Machine-readable diagnostic')
    args=parser.parse_args(argv)
    errors=0
    for path in args.scans:
        try:
            report=diagnose(Path(path))
            if args.json:
                print(json.dumps(report,ensure_ascii=False,indent=2))
            else:
                print(f"\\n{report['source']} [{report['format']}, {report['reader']}]")
                for ch in report['channels']:
                    for tr in ch['traces']:
                        print(f"  {ch['name']} [{ch['unit']}] {tr['trace']}: {tr['shape']} "
                              f"sampled_finite={tr['sampled_finite']} sampled_masked={tr['sampled_masked']}")
                for warning in report['warnings']:
                    print(f'  NOTE: {warning}')
        except Exception as exc:
            errors+=1
            print(f'FAILED {path}: {type(exc).__name__}: {exc}',file=sys.stderr)
    return 1 if errors else 0


if __name__=='__main__':
    raise SystemExit(main())
