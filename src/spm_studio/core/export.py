"""Collision-safe numerical and figure export, with adjacent JSON provenance."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json
import numpy as np
from .models import Scan, ImageStyle, ProcessingStep
from .display import bounds,render_rgb
from .painting import qimage_rgb, paint_frame
from .presets import validate_export, DEFAULT_EXPORT


def unique_target(path: Path):
    path = Path(path)
    if not path.exists():
        return path
    for idx in range(1,100000):
        candidate = path.with_name(f'{path.stem}_{idx:03}{path.suffix}')
        if not candidate.exists():
            return candidate
    raise RuntimeError('Too many matching outputs')


def fingerprint(path: Path):
    st = path.stat()
    h = hashlib.sha256()
    with path.open('rb') as f:
        h.update(f.read(1024*1024))
    return {'size_bytes':st.st_size,'mtime_ns':st.st_mtime_ns,
            'sha256_first_1MiB':h.hexdigest()}


def provenance(scan: Scan, channel, direction, steps, style, preset, extra=None):
    return {'schema_version':1, 'utc':datetime.now(timezone.utc).isoformat(),
            'source':str(scan.path), 'fingerprint':fingerprint(scan.path),
            'channel':channel, 'trace':direction,'geometry':scan.channels[channel].geometry.to_dict(),
            'unit':scan.channels[channel].unit, 'processing':[asdict(s) for s in steps],
            'style':asdict(style),'export_preset':preset,'warnings':scan.warnings,
            'extra':extra or {}}


def export_scan(scan:Scan, channel:str, direction:str, data:np.ndarray,
                steps:list[ProcessingStep], style:ImageStyle, destination:Path,
                preset:dict|None=None, overlays=(), plot_config=None, transparent=None):
    from PySide6.QtGui import QImage, QPainter, QPdfWriter, QPageSize
    from PySide6.QtCore import QSizeF, QSize, QRectF, QRect
    preset = validate_export(preset or DEFAULT_EXPORT)
    if transparent is None:
        transparent = bool((plot_config or {}).get('transparent_background', False))
    dest = unique_target(Path(destination))
    dest.parent.mkdir(parents=True,exist_ok=True)
    suffix = dest.suffix.lower()
    if suffix not in ('.png','.jpg','.jpeg','.svg','.pdf','.npy','.csv'):
        raise ValueError('Supported formats: PNG, JPG, SVG, PDF, NPY, CSV')
    if suffix == '.npy':
        with dest.open('wb') as f:
            np.save(f,data,allow_pickle=False)
    elif suffix == '.csv':
        np.savetxt(dest,data,delimiter=',',fmt='%.12g')
    else:
        frame = qimage_rgb(render_rgb(data,style))
        bnd = bounds(data,style)
        dpi = int(preset['dpi'])
        w,h = max(64,round(preset['width_mm']/25.4*dpi)),max(64,round(preset['height_mm']/25.4*dpi))
        if suffix in ('.png','.jpg','.jpeg'):
            surface = QImage(w,h,QImage.Format.Format_ARGB32)
            from PySide6.QtGui import QColor
            surface.fill(QColor(0,0,0,0) if transparent and suffix=='.png' else QColor('#ffffff'))
            painter = QPainter(surface)
        elif suffix == '.pdf':
            surface = QPdfWriter(str(dest))
            surface.setResolution(dpi)
            surface.setPageSize(QPageSize(QSizeF(preset['width_mm'],preset['height_mm']), QPageSize.Unit.Millimeter))
            w,h = surface.width(),surface.height()
            painter = QPainter(surface)
        else:
            try:
                from PySide6.QtSvg import QSvgGenerator
            except ImportError as exc:
                raise RuntimeError('SVG export requires the PySide6 QtSvg component') from exc
            surface = QSvgGenerator()
            surface.setFileName(str(dest))
            surface.setSize(QSize(w,h))
            surface.setViewBox(QRect(0,0,w,h))
            painter = QPainter(surface)
        paint_frame(painter, frame, bnd, channel, scan.channels[channel].unit,
                    scan.channels[channel].geometry, style, QRectF(0,0,w,h),
                    overlays, font_pt=(plot_config or {}).get('label_size',preset['font_size_pt']),
                    background=('transparent' if transparent and suffix!='.jpg' and suffix!='.jpeg'
                                else (plot_config or {}).get('background','#ffffff')))
        painter.end()
        if suffix in ('.png','.jpg','.jpeg') and not surface.save(str(dest)):
            raise RuntimeError(f'Unable to write {dest}')
    metadata_path = dest.with_name(dest.name+'.provenance.json')
    metadata_path.write_text(json.dumps(provenance(scan,channel,direction,steps,style,preset),
                                        indent=2,ensure_ascii=False,default=str)+'\n',encoding='utf8')
    return dest


# ---------------------------------------------------------------------------
# v31 — tight, transparent-aware rendering shared by every Qt figure export
# ---------------------------------------------------------------------------
def render_tight(dest, draw, width_px, height_px, dpi, *, transparent=False,
                 background='#ffffff', pad_px=None, crop=True):
    """Render ``draw(painter)`` (page coordinates width_px × height_px at ``dpi``)
    to PNG/JPG/PDF/SVG, cropped exactly to the drawn content.

    Pass 1 draws into a transparent probe image to find the bounding box of all
    painted pixels (scan, colourbars, labels, letters).  Pass 2 renders again
    into a page of exactly that size, so there is no empty band above/below or
    left/right of the figure and nothing must be cropped (and upscaled) later.
    Resolution is unchanged: the content keeps its pixel size at ``dpi``.
    Returns a dict with the final pixel size, the crop box and a transparency check.
    """
    from PySide6.QtCore import QRectF, QSizeF, QSize, QRect, QMarginsF
    from PySide6.QtGui import QImage, QPainter, QColor, QPdfWriter, QPageSize, QPageLayout
    dest=Path(dest);suffix=dest.suffix.lower()
    if suffix not in ('.png','.jpg','.jpeg','.pdf','.svg'):
        raise ValueError(f'Unsupported figure format {suffix}')
    W,H=int(width_px),int(height_px)
    if pad_px is None:pad_px=max(2,int(round(dpi/25.4*0.25)))   # 0.25 mm safety pad
    x0,y0,x1,y1=0,0,W,H
    if crop:
        s=min(1.,3000./max(W,H))
        pw,ph=max(1,int(np.ceil(W*s))),max(1,int(np.ceil(H*s)))
        probe=QImage(pw,ph,QImage.Format.Format_ARGB32)
        probe.fill(QColor(0,0,0,0))
        # Same logical DPI as the final device, so point-sized fonts measure identically.
        _dpm=int(round(dpi/0.0254));probe.setDotsPerMeterX(_dpm);probe.setDotsPerMeterY(_dpm)
        p=QPainter(probe)
        p.setRenderHint(QPainter.RenderHint.Antialiasing,True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing,True)
        p.scale(s,s)
        draw(p)
        p.end()
        ptr=probe.constBits()
        a=np.frombuffer(ptr,dtype=np.uint8,count=probe.sizeInBytes()).reshape(ph,probe.bytesPerLine()//4,4)[:,:pw,3]
        ys,xs=np.nonzero(a>6)
        if len(xs):
            extra=int(np.ceil(1/s))+pad_px
            x0=max(0,int(np.floor(xs.min()/s))-extra);y0=max(0,int(np.floor(ys.min()/s))-extra)
            x1=min(W,int(np.ceil((xs.max()+1)/s))+extra);y1=min(H,int(np.ceil((ys.max()+1)/s))+extra)
    bw,bh=max(8,x1-x0),max(8,y1-y0)
    opaque=(not transparent) or suffix in ('.jpg','.jpeg')
    def _paint(painter):
        if opaque:painter.fillRect(QRectF(0,0,bw,bh),QColor(background if background not in ('none','transparent') else '#ffffff'))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing,True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing,True)
        painter.translate(-x0,-y0)
        draw(painter)
    if suffix in ('.png','.jpg','.jpeg'):
        img=QImage(bw,bh,QImage.Format.Format_ARGB32)
        img.fill(QColor(0,0,0,0) if not opaque else QColor('#ffffff'))
        dpm=int(round(dpi/0.0254));img.setDotsPerMeterX(dpm);img.setDotsPerMeterY(dpm)
        painter=QPainter(img);_paint(painter);painter.end()
        if suffix!='.png':img=img.convertToFormat(QImage.Format.Format_RGB32)
        if not img.save(str(dest),None,100 if suffix!='.png' else -1):
            raise RuntimeError(f'Unable to write {dest}')
    elif suffix=='.pdf':
        writer=QPdfWriter(str(dest));writer.setResolution(int(dpi))
        writer.setPageLayout(QPageLayout(QPageSize(QSizeF(bw/dpi*25.4,bh/dpi*25.4),QPageSize.Unit.Millimeter,
                                         '',QPageSize.SizeMatchPolicy.ExactMatch),
                                         QPageLayout.Orientation.Portrait,QMarginsF(0,0,0,0),
                                         QPageLayout.Unit.Millimeter))
        painter=QPainter(writer);_paint(painter);painter.end()
    else:
        from PySide6.QtSvg import QSvgGenerator
        gen=QSvgGenerator();gen.setFileName(str(dest));gen.setSize(QSize(bw,bh))
        gen.setViewBox(QRect(0,0,bw,bh));gen.setResolution(int(dpi))
        painter=QPainter(gen);_paint(painter);painter.end()
    check=None
    if suffix=='.png' and transparent:
        saved=QImage(str(dest))
        corners=[saved.pixelColor(x,y).alpha() for x,y in ((0,0),(bw-1,0),(0,bh-1),(bw-1,bh-1))]
        check={'corner_alpha':corners,'transparent_ok':min(corners)==0 or saved.hasAlphaChannel()}
    return {'size_px':[bw,bh],'size_mm':[bw/dpi*25.4,bh/dpi*25.4],'crop_box_px':[x0,y0,x1,y1],
            'page_px':[W,H],'transparent':bool(transparent and not opaque),'png_check':check}
