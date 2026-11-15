"""Physical, non-destructive multichannel alpha composition and publication figures.

The same compositing function is used by the live preview and the export module.
All layers must share the raster geometry.  No arbitrary resizing/registration is
performed, because that could create physically misleading alignment.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import numpy as np
from .display import bounds, render_rgb
from .models import ImageStyle, Geometry


@dataclass
class Layer:
    name: str
    data: np.ndarray
    unit: str = ''
    palette: str = 'gray'
    opacity: float = 1.
    gamma: float = 1.


def make_layers(base_name, base_data, base_unit, names, data_provider, units, parameters,
                *, skip_duplicates=False, skipped=None):
    """Construct the overlay stack (bottom → top).

    Normally layer 1 (bottom) is the channel shown in the viewer and layers 2–5
    are the chosen channels.  With ``skip_duplicates`` (interactive use):

    * if the viewer channel is itself one of the chosen layers, the stack is
      exactly the chosen layers in their order (no "used twice" error: the
      viewer channel is not counted as an extra layer);
    * any other repeated channel is ignored and reported in ``skipped``.
    Without ``skip_duplicates`` a repeated channel raises (strict mode).
    """
    palettes=['inferno','viridis','ice','ruby']
    explicit=[]
    for i in range(2,6):
        name=str(parameters.get(f'channel_{i}','') or '').strip()
        if not name or name.lower() in ('(none)','none','off'):
            if i==2: raise ValueError('Choose a second, different channel.')
            continue
        explicit.append((name,float(parameters.get(f'opacity_{i}',.45)),
                         str(parameters.get(f'palette_{i}',palettes[(i-2)%len(palettes)]))))
    extra=str(parameters.get('additional_channels','') or '').strip()
    if extra:
        for name in (x.strip() for x in extra.split(',')):
            if name:
                explicit.append((name,float(parameters.get('additional_opacity',.4)),
                                 palettes[(len(explicit)+1)%len(palettes)]))
    def data_of(name):
        return np.asarray(base_data) if name==base_name else np.asarray(data_provider(name))
    chosen=set();layers=[]
    if skip_duplicates and any(n==base_name for n,_,_ in explicit):
        stack=explicit
    else:
        layers.append(Layer(base_name,np.asarray(base_data),base_unit,'gray',1.))
        chosen.add(base_name)
        stack=explicit
    for name,alpha,palette in stack:
        if name in chosen:
            if not skip_duplicates:raise ValueError(f'Channel {name!r} selected more than once')
            if skipped is not None:skipped.append(name)
            continue
        chosen.add(name)
        unit=base_unit if name==base_name else units.get(name,'')
        layers.append(Layer(name,data_of(name),unit,palette,1. if not layers else alpha))
    if len(layers)<2:
        raise ValueError(f'At least two different channels are needed (only {layers[0].name if layers else "none"} '
                         f'selected). Choose another channel for layer 2 or 3.')
    return layers


def composite(layers, *, max_dimension=None):
    """Blend native, pixel-aligned measurements; return RGB and exact SI limits."""
    if len(layers)<2:raise ValueError('Select at least two channels')
    shape=np.shape(layers[0].data)
    if len(shape)!=2:raise ValueError('Only two-dimensional scan channels are supported')
    stride=max(1,int(np.ceil(max(shape)/max_dimension))) if max_dimension else 1
    result=None
    legend=[]
    for index,layer in enumerate(layers):
        a=np.asarray(layer.data)
        if a.shape!=shape:raise ValueError(f'{layer.name}: {a.shape} differs from base {shape}. Registration required; not resized.')
        alpha=float(layer.opacity)
        if not np.isfinite(alpha) or not 0<=alpha<=1:
            raise ValueError(f'Opacity of {layer.name} must be from 0 to 1')
        style=ImageStyle(colormap=layer.palette,gamma=layer.gamma,range_mode='percentile',low=2,high=98)
        lo,hi=bounds(a,style)
        sub=a[::stride,::stride]
        color=render_rgb(sub,style,fixed_bounds=(lo,hi)).astype(np.float32)
        finite=np.isfinite(sub)
        if index==0:
            result=color
        else:
            effective=alpha*finite[...,None]
            result=result*(1-effective)+color*effective
        legend.append((layer,style,lo,hi))
    return np.clip(np.rint(result),0,255).astype('uint8'),legend


def save_publication(layers,geometry:Geometry,output_dir:Path,*,formats=('png','pdf','svg'),
                     width_mm=178.,dpi=600,show_colorbars=True,transparent=False):
    """Export at publication scale. Qt keeps scalebars/labels/colorbars vector in PDF/SVG.

    Only the measured scan image remains a raster; the figure never claims higher
    physical scan resolution than the source pixels.
    """
    from PySide6.QtGui import QGuiApplication
    import os
    if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    _qt_app=QGuiApplication.instance() or QGuiApplication([])
    from PySide6.QtCore import QRectF,QSizeF,QSize,QRect,Qt
    from PySide6.QtGui import QImage,QPainter,QColor,QPdfWriter,QPageSize,QFont
    from .painting import qimage_rgb,draw_colorbar,_draw_gwyddion_scale_bar
    from .models import preferred_display_unit
    from .export import unique_target
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    rgb,legend=composite(layers)
    scan=qimage_rgb(rgb)
    physical_aspect=(geometry.size_m[0]/geometry.size_m[1] if geometry.size_m else rgb.shape[1]/rgb.shape[0])
    physical_aspect=max(.03,float(physical_aspect))
    n_bars=len(legend) if show_colorbars else 0
    # Pixel units on the painter derive from the selected physical paper/DPI.
    margin_mm=7.
    scan_width_mm=width_mm-2*margin_mm
    scan_height_mm=min(125.,scan_width_mm/physical_aspect)
    bar_row_mm=5.7 if show_colorbars else 0
    height_mm=max(65.,scan_height_mm+margin_mm*2+bar_row_mm*n_bars+8.)
    created=[]
    px_per_mm=dpi/25.4
    W=max(200,int(round(width_mm*px_per_mm)))
    Hpx=max(200,int(round(height_mm*px_per_mm)))
    from .display import lut as palette_lut
    def draw(painter):
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,False)
        w=W;scale=w/width_mm
        sw=scan_width_mm*scale;sh=scan_height_mm*scale
        scan_rect=QRectF((w-sw)/2,margin_mm*scale,sw,sh)
        painter.drawImage(scan_rect,scan)
        if geometry.size_m:
            _draw_gwyddion_scale_bar(painter,scan_rect,geometry.size_m[0],
                                    font_pt=9*scale/2.5,position='bottom_right',color='#ffffff')
        legend_font=QFont('DejaVu Sans');legend_font.setPixelSize(max(9,int(2.8*scale)))
        painter.setFont(legend_font)
        # Small vector legend in image top left; separate quantitative bars below.
        for idx, (layer,style,lo,hi) in enumerate(legend):
            text=f'{layer.name} · {int(round(layer.opacity*100))}%'
            tr=QRectF(scan_rect.left()+2*scale,scan_rect.top()+(2+idx*4.0)*scale,
                       scan_rect.width()*.83,3.6*scale)
            painter.fillRect(tr,QColor(0,0,0,165))
            rr,gg,bb=map(int,palette_lut(layer.palette)[176])
            painter.fillRect(QRectF(tr.left()+.35*scale,tr.top()+.6*scale,
                                    2.4*scale,2.4*scale),QColor(rr,gg,bb))
            painter.setPen(QColor('white'))
            painter.drawText(QRectF(tr.left()+3.4*scale,tr.top(),tr.width()-3.5*scale,tr.height()),
                             Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,text)
        if show_colorbars:
            for idx,(layer,style,lo,hi) in enumerate(legend):
                row_h=bar_row_mm*scale
                anchor=QRectF(scan_rect.left(),scan_rect.bottom()+idx*row_h,scan_rect.width(),0)
                draw_colorbar(painter,anchor,style,lo,hi,layer.name,'',
                              position='below',font_px=max(9,int(2.3*scale)),base_unit=layer.unit,
                              outside_text_color='#202020')
    from .export import render_tight
    for ext in formats:
        ext=ext.lower().lstrip('.')
        if ext not in ('png','pdf','svg'):continue
        out=unique_target(output_dir/f'channel_overlay.{ext}')
        # v31: page cropped exactly to the figure, optional transparent page.
        render_tight(out,draw,W,Hpx,dpi,transparent=transparent)
        created.append(out)
    return created


# ---------------------------------------------------------------------------
# v29 — animated layer-by-layer transparency sweep (GIF / optional MP4)
# ---------------------------------------------------------------------------
def _layer_rgb_stack(layers):
    """Full-resolution RGB of every layer with the same ranges as composite()."""
    shape=np.shape(layers[0].data)
    rgbs=[];finite=[];legend=[]
    for layer in layers:
        a=np.asarray(layer.data)
        if a.shape!=shape:
            raise ValueError(f'{layer.name}: {a.shape} differs from base {shape}. Registration required; not resized.')
        style=ImageStyle(colormap=layer.palette,gamma=layer.gamma,range_mode='percentile',low=2,high=98)
        lo,hi=bounds(a,style)
        rgbs.append(render_rgb(a,style,fixed_bounds=(lo,hi)).astype(np.float32))
        finite.append(np.isfinite(a)[...,None].astype(np.float32))
        legend.append((layer,style,lo,hi))
    return rgbs,finite,legend


def sweep_opacities(n_layers, t, start=0., end=1.):
    """Opacity of every layer at normalized time t∈[0,1].

    t=0 → only the lowest (base) channel; layer 2 then fades from 0 → 1, then
    layer 3 fades 0 → 1 on top of it, … ; t=1 → the top layer is fully opaque
    and none of the lower layers remains visible.
    """
    n_top=max(1,n_layers-1)
    t=float(np.clip(t,0.,1.))
    start=float(np.clip(start,0.,1.));end=float(np.clip(end,0.,1.))
    alphas=[1.]
    for k in range(n_top):
        f=float(np.clip(t*n_top-k,0.,1.))
        alphas.append(start+(end-start)*f)
    return alphas


def sweep_frame(rgbs, finite, alphas):
    result=rgbs[0].copy()
    for rgb,ok,a in zip(rgbs[1:],finite[1:],alphas[1:]):
        if a<=0:continue
        eff=a*ok
        result=result*(1-eff)+rgb*eff
    return np.clip(np.rint(result),0,255).astype('uint8')


def _smoothstep(x):
    return x*x*(3-2*x)


def _font(size_px):
    from PIL import ImageFont
    candidates=['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
                '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    try:
        import matplotlib
        candidates.insert(0,str(Path(matplotlib.get_data_path())/'fonts'/'ttf'/'DejaVuSans-Bold.ttf'))
    except Exception:pass
    for c in candidates:
        try:return ImageFont.truetype(c,int(size_px))
        except OSError:continue
    try:return ImageFont.load_default(size=int(size_px))
    except TypeError:return ImageFont.load_default()


def _nice_length(target):
    if target<=0:return 0.
    order=10**np.floor(np.log10(target))
    for k in (5,2,1):
        if k*order<=target:return float(k*order)
    return float(order)


def _annotate(img, geometry, layers, alphas, *, scale_bar=True, labels=True):
    from PIL import ImageDraw
    draw=ImageDraw.Draw(img,'RGBA')
    W,H=img.size
    unit=max(W,H)/100.
    if labels:
        font=_font(max(12,2.6*unit))
        y=1.6*unit
        # Visible weight of each channel in the current frame (what the eye sees):
        # its own opacity × transparency of every layer above it.
        visible=[]
        for i,a in enumerate(alphas):
            v=a
            for b in alphas[i+1:]:v*=(1-b)
            visible.append(v)
        for layer,a in zip(layers,visible):
            text=f'{layer.name}  {int(round(a*100)):3d}%'
            bbox=draw.textbbox((0,0),text,font=font)
            tw,th=bbox[2]-bbox[0],bbox[3]-bbox[1]
            draw.rectangle([1.6*unit,y,1.6*unit+tw+1.8*unit,y+th+1.2*unit],fill=(0,0,0,int(70+110*a)))
            draw.text((2.5*unit,y+.5*unit-bbox[1]),text,font=font,fill=(255,255,255,int(110+145*a)))
            y+=th+1.8*unit
    if scale_bar and geometry is not None and geometry.size_m:
        width_m=float(geometry.size_m[0])
        if width_m>0:
            if width_m<1e-6:mult,u=1e9,'nm'
            elif width_m<1e-3:mult,u=1e6,'µm'
            else:mult,u=1e3,'mm'
            length=_nice_length(width_m*mult/5)
            px=length/(width_m*mult)*W
            font=_font(max(12,2.8*unit))
            x1=W-3*unit;x0=x1-px;yb=H-3.2*unit
            text=f'{length:g} {u}'
            bbox=draw.textbbox((0,0),text,font=font)
            th=bbox[3]-bbox[1];tw=bbox[2]-bbox[0]
            draw.rectangle([x0-.9*unit,yb-th-2.6*unit,x1+.9*unit,yb+1.6*unit],fill=(0,0,0,95))
            draw.rectangle([x0,yb-.45*unit,x1,yb+.45*unit],fill=(255,255,255,255))
            draw.text(((x0+x1)/2-tw/2,yb-th-1.5*unit-bbox[1]),text,font=font,fill=(255,255,255,255))
    return img


def save_overlay_animation(layers, geometry, path, *, duration_s=6., fps=20, max_px=1440,
                           hold_fraction=.10, ease=True, scale_bar=True, labels=True,
                           also_mp4=False, progress=None, start_opacity=0., end_opacity=1.):
    """Write a presentation-quality GIF of the layer-by-layer opacity sweep.

    * Frame 0 shows the lowest (base) channel only; each higher layer fades in
      to 100 %, in order; the last frame shows only the top layer.
    * Native scan pixels are enlarged with nearest-neighbour replication only
      (crisp, no invented detail) to ``max_px`` on the longest side, respecting
      the calibrated physical aspect ratio.
    * One global adaptive 256-colour palette for all frames (no flicker) with
      Floyd–Steinberg dithering for smooth colour gradients.
    * ``also_mp4`` additionally writes a lossless-looking H.264 MP4 (CRF 12)
      next to the GIF when ffmpeg is installed – best for PowerPoint/Keynote.
    Returns the list of written files.
    """
    from PIL import Image
    path=Path(path)
    if path.suffix.lower()!='.gif':path=path.with_suffix('.gif')
    path.parent.mkdir(parents=True,exist_ok=True)
    if len(layers)<2:raise ValueError('Select at least two channels for an animation')
    duration_s=float(duration_s);fps=int(fps);max_px=int(max_px)
    if not (0.5<=duration_s<=120):raise ValueError('GIF duration must be 0.5–120 s')
    if not (2<=fps<=50):raise ValueError('Frame rate must be 2–50 fps')
    if not (64<=max_px<=4096):raise ValueError('GIF size must be 64–4096 px')
    rgbs,finite,_legend=_layer_rgb_stack(layers)
    ny,nx=rgbs[0].shape[:2]
    if geometry is not None and getattr(geometry,'size_m',None):
        aspect=float(geometry.size_m[0])/float(geometry.size_m[1])
    else:aspect=nx/ny
    aspect=max(.03,min(33.,aspect))
    if aspect>=1:W,H=max_px,max(16,int(round(max_px/aspect)))
    else:W,H=max(16,int(round(max_px*aspect))),max_px
    # GIF frame delays are stored in 1/100 s; browsers clamp < 20 ms.
    delay_cs=max(2,int(round(100/fps)))
    n=max(2,int(round(duration_s*100/delay_cs)))
    hold=int(round(n*float(np.clip(hold_fraction,0,.4))))
    ramp=max(2,n-2*hold)
    times=[0.]*hold+list(np.linspace(0,1,ramp))+[1.]*hold
    n_layers=len(layers)
    frames_rgb=[]
    for i,t in enumerate(times):
        if ease:
            # Ease each layer's own fade so every channel sweep starts/ends softly.
            n_top=n_layers-1
            seg=min(n_top-1,int(t*n_top)) if t<1 else n_top-1
            local=t*n_top-seg
            t=(seg+_smoothstep(float(np.clip(local,0,1))))/n_top
        alphas=sweep_opacities(n_layers,t,start_opacity,end_opacity)
        frame=Image.fromarray(sweep_frame(rgbs,finite,alphas),'RGB').resize((W,H),Image.NEAREST)
        if scale_bar or labels:
            frame=_annotate(frame,geometry,layers,alphas,scale_bar=scale_bar,labels=labels)
        frames_rgb.append(frame)
        if progress:progress(int(70*(i+1)/len(times)))
    # One palette for the whole animation, from evenly spaced key frames.
    keys=frames_rgb[::max(1,len(frames_rgb)//12)][:12]
    thumb_w=min(W,720);thumb_h=max(1,int(round(H*thumb_w/W)))
    mosaic=Image.new('RGB',(thumb_w,thumb_h*len(keys)))
    for k,f in enumerate(keys):mosaic.paste(f.resize((thumb_w,thumb_h),Image.NEAREST),(0,k*thumb_h))
    palette=mosaic.quantize(colors=256,method=Image.Quantize.MEDIANCUT,dither=Image.Dither.NONE)
    frames=[]
    for i,f in enumerate(frames_rgb):
        frames.append(f.quantize(palette=palette,dither=Image.Dither.FLOYDSTEINBERG))
        if progress:progress(70+int(25*(i+1)/len(frames_rgb)))
    durations=[delay_cs*10]*len(frames)
    frames[0].save(path,save_all=True,append_images=frames[1:],duration=durations,
                   loop=0,optimize=False,disposal=1)
    written=[path]
    if also_mp4:
        import shutil,subprocess,tempfile
        ff=shutil.which('ffmpeg')
        if ff:
            mp4=path.with_suffix('.mp4')
            w2,h2=W-(W%2),H-(H%2)
            cmd=[ff,'-y','-loglevel','error','-f','rawvideo','-pix_fmt','rgb24','-s',f'{w2}x{h2}',
                 '-r',f'{100/delay_cs:.4f}','-i','-','-c:v','libx264','-preset','slow','-crf','12',
                 '-pix_fmt','yuv420p','-movflags','+faststart',str(mp4)]
            proc=subprocess.Popen(cmd,stdin=subprocess.PIPE)
            for f in frames_rgb:
                proc.stdin.write(np.asarray(f.crop((0,0,w2,h2)),dtype=np.uint8).tobytes())
            proc.stdin.close();proc.wait()
            if proc.returncode==0:written.append(mp4)
    meta={'kind':'spm_studio_channel_overlay_animation','schema_version':1,
          'order_bottom_to_top':[l.name for l in layers],
          'palettes':[l.palette for l in layers],
          'duration_s':len(frames)*delay_cs/100,'fps':100/delay_cs,'frames':len(frames),
          'size_px':[W,H],'source_shape_yx':[ny,nx],'upscaling':'nearest-neighbour (no interpolation)',
          'hold_fraction':hold_fraction,'easing':bool(ease),
          'opacity_range':[float(start_opacity),float(end_opacity)],
          'files':[str(x) for x in written]}
    import json
    path.with_suffix('.gif.json').write_text(json.dumps(meta,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    if progress:progress(100)
    return written
