"""Official multichannel transparency module, using the shared Studio renderer."""
from pathlib import Path
import json
import numpy as np
from spm_studio.core.channel_overlay import make_layers, composite, save_publication


def run(ctx):
    p=dict(ctx.parameters)
    def image(name):
        # Validate same calibrated physical geometry through ModuleContext.
        return ctx.image(name,ctx.direction)
    ctx.progress(5,'Reading physically registered scan channels')
    _skipped=[]
    layers=make_layers(ctx.channel,ctx.data,ctx.unit,[],image,ctx.channel_units or {},p,
                       skip_duplicates=True,skipped=_skipped)
    if _skipped:
        ctx.log('Ignored layer(s) already used lower in the stack: '+', '.join(dict.fromkeys(_skipped))+
                f' (layer 1 = viewer channel {ctx.channel})','warning')
    # Require geometries of each layer to be identical, not only the pixel grid.
    from spm_studio.core.models import Geometry
    for layer in layers[1:]:
        geom=Geometry.from_dict(ctx.channel_geometries[layer.name])
        own=ctx.geometry
        if geom.shape!=own.shape or geom.size_m!=own.size_m or geom.center_m!=own.center_m or geom.angle_deg!=own.angle_deg:
            raise ValueError(f'{layer.name}: calibrated geometry differs from base; cannot overlay without explicit registration')
    try:
        from spm_studio.core.plot_settings import viewer_channel
        _info=viewer_channel(getattr(ctx,'plot_config',None) or {},layers[0].name)
        if _info and _info.get('colormap'):
            from spm_studio.core.display import lut as _lut
            _lut(_info['colormap']);layers[0].palette=_info['colormap']   # v34: base layer as shown on the scan
    except Exception:
        pass
    ctx.progress(30,'Compositing full-resolution channels')
    # Validate pixels and alpha even if a transparency is set to zero.
    rgb,legend=composite(layers)
    ctx.progress(60,'Rendering publication figures')
    files=save_publication(layers,ctx.geometry,ctx.output_dir,formats=('png','pdf','svg'),
                           width_mm=float(p.get('export_width_mm',178.)),
                           dpi=int(p.get('export_dpi',600)),
                           show_colorbars=bool(p.get('show_colorbars',True)),
                           transparent=bool((getattr(ctx,'plot_config',None) or {}).get('transparent_background',False)))
    for item in files:ctx.result_file(item,'Channel overlay · '+item.suffix.upper().lstrip('.'))
    record={'kind':'spm_studio_channel_overlay','schema_version':1,'source_scan':str(ctx.scan_path),
            'trace':ctx.direction,'geometry':ctx.geometry.to_dict(),
            'layers':[{'channel':x.name,'unit':x.unit,'palette':x.palette,'opacity':x.opacity,
                       'range_si':[float(lo),float(hi)]}
                      for x,_,lo,hi in legend],
            'quality':{'dpi':p.get('export_dpi',600),'source_shape_yx':list(ctx.data.shape),
                       'raster_pixels_not_interpolated':True,'pdf_svg_annotations_vector':True},
            'figure_files':list(map(str,files))}
    manifest=ctx.output_dir/'channel_overlay.json'
    manifest.write_text(json.dumps(record,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    ctx.result_file(manifest,'Channel opacity and calibration metadata')
    ctx.result_table(['channel','palette','opacity','low (SI)','high (SI)'],
                     [[layer.name,layer.palette,layer.opacity,lo,hi] for layer,_,lo,hi in legend],
                     'Displayed layers (visualization only)')
    ctx.progress(100,'Publication overlay saved')
