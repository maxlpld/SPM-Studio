"""Calibrated molecule placement on a COPY of the prior lattice ROI result."""
from __future__ import annotations
import json
import numpy as np
from pathlib import Path
from lattice_artifacts import write_gwy
from placement_engine import find_lattice_result, prepare_artwork, render_molecules, view_for_session_crop


def run(ctx):
    p=dict(ctx.parameters)
    source,doc=find_lattice_result(ctx.scan_path,p.get('lattice_result_json',''))
    doc=view_for_session_crop(doc,(getattr(ctx,'metadata',{}) or {}).get('session_crop'))
    ctx.log(f'Using lattice ROI produced by {source}')
    ctx.log('Artwork placement is a geometric registry hypothesis, NOT an adsorption or DFT prediction.')
    picture,art_info=prepare_artwork(p.get('molecule_image',''),p,target_long_side=2400)
    ctx.log('Artwork scale: canvas {0}×{1} px, visible molecule {2}×{3} px{4}; '
            '{5:.4g} × {6:.4g} nm per artwork pixel'.format(*art_info['artwork_canvas_px'],
            *art_info['visible_molecule_px'],' (empty margins trimmed)' if art_info['trimmed'] else '',
            *art_info['nm_per_artwork_px']))
    if abs(art_info['artwork_aspect_px']/art_info['requested_aspect_nm']-1)>.15:
        ctx.log('Molecule width/height ratio differs by >15 % from the artwork aspect ratio: '
                'the drawing will be stretched. Set one size to 0 to keep the artwork aspect.','warning')
    ctx.progress(10,'Calibrating molecular artwork from ROI metadata')
    image,count,rotation,sites=render_molecules(doc,picture,p,max_preview_side=(None if p.get('export_gwy') else 640),
                                                 plot_config=getattr(ctx,'plot_config',None))
    # v0.8: the figure is drawn by the SAME renderer as Export… (gap, scale bar,
    # fonts, page size, colormap of the scan); molecules stay vector objects.
    from vector_publication import export_placement
    cfg=getattr(ctx,'plot_config',None) or {'schema_version':1}
    p['_transparent_background']=bool(cfg.get('transparent_background',False))
    publication=export_placement(doc,p.get('molecule_image',''),picture,p,sites,rotation,
                                  ctx.output_dir,plot_config=cfg,formats=getattr(ctx,'plot_formats',('svg',)),
                                  scan_path=ctx.scan_path)
    for file in publication:
        ctx.result_file(file,'Lattice with molecules · '+file.suffix[1:].upper())
    gwy=None
    if bool(p.get('export_gwy',False)):
        ctx.progress(75,'Preparing independent annotated Gwyddion copy')
        gwy=ctx.output_dir/'lattice_plus_molecules.gwy'
        original=(doc['_raw_view'] if '_raw_view' in doc else
                  np.load(doc['cropped_scan_npy'],mmap_mode='r'))
        from lattice_artifacts import normalize_gray,lattice_draw
        lattice_render=lattice_draw(normalize_gray(original),doc['basis_local_nm'],
                      doc['roi_geometry'],colors=tuple(doc.get('vector_colors',('#16d8f5','#fbb748'))),
                      legend_corner=doc.get('vector_legend_corner','top_left'))
        lattice_image=np.asarray(lattice_render.convert('L'),dtype=float)
        molecule_image=np.asarray(image.convert('L').resize((original.shape[1],original.shape[0]),__import__('PIL.Image',fromlist=['Resampling']).Resampling.LANCZOS),dtype=float)
        try:
            write_gwy(gwy,[(doc['source_channel']+' (cropped '+doc['source_direction']+')',original,doc.get('source_unit','')),
                           ('Lattice vectors (display only)',lattice_image,'a.u.'),
                           ('Lattice + molecule artwork (display only)',molecule_image,'a.u.')],
                      doc['roi_geometry'],basis_local_nm=doc['basis_local_nm'],
                      extra_metadata={'Molecule width (nm)':p['molecule_width_nm'],
                         'Molecule height (nm)':p['molecule_height_nm'],
                         'Molecule rotation (deg)':rotation,'Lattice a (nm)':doc['a_nm'],
                         'Lattice b (nm)':doc['b_nm'],'Lattice gamma (deg)':doc['gamma_deg']})
            ctx.result_file(gwy,'Calibrated GWY with original ROI + two separate annotation channels')
        except Exception as exc:
            ctx.log('Could not write molecule GWY: '+str(exc),'warning')
            gwy=None
    record={'schema_version':1,'kind':'spm_studio_molecule_placement',
            'lattice_result':str(source),'source_scan':doc['source_scan'],
            'pixel_size_nm':doc['roi_geometry']['pixel_size_nm'],
            'session_crop':(getattr(ctx,'metadata',{}) or {}).get('session_crop'),
            'visible_roi_geometry':doc['roi_geometry'],
            'roi_size_nm':doc['roi_geometry']['size_nm'],
            'basis_local_nm':doc['basis_local_nm'],
            'molecule_png':str(Path(p['molecule_image']).resolve()),
            'molecule_png_pixels':list(picture.size),'artwork_scale':art_info,'width_nm':float(p['molecule_width_nm']),
            'height_nm':float(p['molecule_height_nm']),'rotation_deg':rotation,
            'origin_offset_nm':[float(p.get('origin_x_nm',0)),float(p.get('origin_y_nm',0))],
            'count':count,'requested_count':int(p.get('molecule_count',0) or 0),
            'lattice_sites':[[cx,cy,i,j] for cx,cy,i,j in sites],
            'publication_figures':[str(f) for f in publication],
            'molecules_gwy':str(gwy) if gwy else None,
            'limitations':'Geometrical lattice sites, not molecular adsorption predictions; physical orientation requires instrument verification.'}
    manifest=ctx.output_dir/'molecule_placement.json'
    manifest.write_text(json.dumps(record,indent=2,ensure_ascii=False),encoding='utf8')
    ctx.result_file(manifest,'Molecule scale, rotation, and lattice site coordinates')
    ctx.result_table(['quantity','value','unit'],[
        ['molecule width',p['molecule_width_nm'],'nm'],['molecule height',p['molecule_height_nm'],'nm'],
        ['rotation',rotation,'deg'],['molecule count',count,'sites']], 'Calibrated placement')
    ctx.log(f'{count} molecules placed, angle {rotation:.2f}°, width {p["molecule_width_nm"]} nm × height {p["molecule_height_nm"]} nm')
    ctx.progress(100,'Calibrated molecule placement saved')
