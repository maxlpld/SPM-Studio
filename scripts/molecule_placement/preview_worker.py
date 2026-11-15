"""Isolated persistent preview process. JSON lines in, JSON lines out.

No GUI libraries or scientific model code are imported by Studio itself.
The worker is started only after user authorization of this module.
"""
from __future__ import annotations
import base64
from io import BytesIO
import json
import sys
from placement_engine import find_lattice_result,prepare_artwork,render_molecules,view_for_session_crop


def process(command):
    seq=int(command['sequence'])
    try:
        params=dict(command['parameters'])
        _,doc=find_lattice_result(command['scan_path'],params.get('lattice_result_json',''))
        doc=view_for_session_crop(doc,command.get('session_crop'))
        params.update({k:float(params[k] or 0) for k in ('molecule_width_nm','molecule_height_nm',
                      'rotation_offset_deg','origin_x_nm','origin_y_nm','opacity')})
        source,art_info=prepare_artwork(params.get('molecule_image',''),params,target_long_side=1200)
        params['max_molecules']=int(params['max_molecules'])
        params['molecule_count']=int(params.get('molecule_count',0) or 0)
        preview,count,angle,_=render_molecules(doc,source,params,max_preview_side=1050,
                                               plot_config=command.get('plot_config'))
        img=BytesIO()
        preview.save(img,'PNG')
        return {'sequence':seq,'ok':True,'image_png_base64':base64.b64encode(img.getvalue()).decode('ascii'),
                'count':count,'rotation_deg':angle,'roi_size_nm':doc['roi_geometry']['size_nm'],
                'nm_per_pixel':doc['roi_geometry']['pixel_size_nm'],
                'site_sampling':count>260,'artwork_scale':art_info}
    except (OSError,ValueError,TypeError,KeyError,RuntimeError,ImportError) as exc:
        return {'sequence':seq,'ok':False,'message':f'{type(exc).__name__}: {exc}'[:350]}


def main():
    for line in sys.stdin:
        try:
            command=json.loads(line)
            response=process(command)
        except (ValueError,TypeError,KeyError) as exc:
            response={'sequence':-1,'ok':False,'message':str(exc)[:350]}
        sys.stdout.write(json.dumps(response,ensure_ascii=False)+'\n')
        sys.stdout.flush()


if __name__=='__main__':main()
