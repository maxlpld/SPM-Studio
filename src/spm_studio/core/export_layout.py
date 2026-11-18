"""Publication layout of independently chosen scan/result panels."""
from __future__ import annotations
from pathlib import Path
import json
import math
import numpy as np
from .display import bounds, lut, render_rgb
from .models import Geometry, ImageStyle, preferred_display_unit
from .plot_settings import default_channel_title, default_scale_bar_color
from .painting import qimage_rgb, _draw_overlays, draw_colorbar, _draw_gwyddion_scale_bar
from .export import unique_target, fingerprint
from .presets import validate_export
from .processing import display_zero_enabled


def find_lattice_manifest(pdf_path:Path):
    pdf_path=Path(pdf_path).resolve()
    if '__' in pdf_path.name and pdf_path.parent.name in ('Images','Plots'):
        run_folder=pdf_path.name.split('__',1)[0]
        candidate=pdf_path.parent.parent/'Data'/run_folder/'lattice_result.json'
        if candidate.is_file():return candidate
    for folder in (pdf_path.parent,pdf_path.parent.parent):
        candidate=folder/'lattice_result.json'
        if candidate.is_file():return candidate
    return None


def panel_defaults(scan, choice, trace='forward'):
    if choice['kind']=='channel':
        name=choice['channel'];ch=scan.channels[name]
        return {'kind':'channel','channel':name,'trace':trace if trace in ch.traces else next(iter(ch.traces)),
                'title':default_channel_title(name),'unit':ch.unit,'colorbar_position':'below',
                'scale_bar_color':default_scale_bar_color(name),'scale_bar_position':'bottom_right'}
    path=Path(choice['path'])
    # A lattice run also exports FFT plots, which must remain actual plots.
    # Only its numeric-overlay artifacts can be reconstructed with a colourbar.
    is_lattice_overlay=(path.stem in {'07_reference_scan_lattice_overlay','lattice_preview'} or
                        path.stem.endswith('__07_reference_scan_lattice_overlay') or
                        path.stem.endswith('__lattice_preview'))
    manifest=find_lattice_manifest(path) if is_lattice_overlay else None
    if manifest:
        info=json.loads(manifest.read_text(encoding='utf-8'))
        if info.get('cropped_scan_npy') and Path(info['cropped_scan_npy']).is_file():
            return {'kind':'lattice','path':str(path),'manifest':str(manifest),
                    'style':_manifest_style(info),
                    'title':str(info.get('colorbar_title') or default_channel_title(str(info.get('source_channel','Lattice')))),
                    'unit':str(info.get('source_unit','')),
                    'colorbar_position':'below','scale_bar_color':default_scale_bar_color(str(info.get('source_channel',''))),
                    'scale_bar_position':'bottom_right',
                    'display_zero':bool(info.get('colorbar_zero_reference',False))}
    return {'kind':'report','path':str(path),'title':path.stem,'unit':'','colorbar_position':'none','scale_bar_color':'#111111','scale_bar_position':'bottom_right'}


def _best_report_source(path):
    """Prefer the vector sibling of a raster script result (same name .svg, then .pdf).

    Scripts save PNG previews next to SVG/PDF masters; using the master avoids the
    pixelation seen when results are combined side by side at publication size.
    """
    path=Path(path)
    if path.suffix.lower() in ('.png','.jpg','.jpeg'):
        for ext in ('.svg','.pdf'):
            sib=path.with_suffix(ext)
            if sib.is_file():return sib
    return path


def key_out_page_background(rgba, *, tolerance=6):
    """Make the white page around a plot transparent (border-connected only).

    Pure-white pixels that touch the image border through other white pixels are
    the page; white *inside* closed frames (plot areas, scans) is untouched.
    ``rgba`` is an (H, W, 4) uint8 array; a new array is returned.
    """
    out=np.array(rgba,copy=True)
    white=(out[...,:3].min(axis=2)>=255-tolerance)&(out[...,3]>0)
    if not white.any():return out
    try:
        from scipy import ndimage
        labels,_=ndimage.label(white)
        edge=np.unique(np.concatenate([labels[0],labels[-1],labels[:,0],labels[:,-1]]))
        page=np.isin(labels,edge[edge>0])
    except ImportError:
        page=np.zeros_like(white)
        page[0]=white[0];page[-1]=white[-1];page[:,0]=white[:,0];page[:,-1]=white[:,-1]
    out[page,3]=0
    return out


def _qimage_key_white(image):
    from PySide6.QtGui import QImage
    img=image.convertToFormat(QImage.Format.Format_RGBA8888)
    w,h=img.width(),img.height()
    arr=np.frombuffer(img.constBits(),dtype=np.uint8,count=img.sizeInBytes()).reshape(h,img.bytesPerLine()//4,4)[:,:w]
    keyed=np.ascontiguousarray(key_out_page_background(arr))
    return QImage(keyed.data,w,h,4*w,QImage.Format.Format_RGBA8888).copy()


def _draw_image_with_aspect(painter, source, frame, aspect):
    from PySide6.QtCore import QRectF
    available_ratio=frame.width()/max(1.,frame.height())
    if aspect>available_ratio:
        width=frame.width();height=width/max(.01,aspect)
    else:
        height=frame.height();width=height*aspect
    r=QRectF(frame.center().x()-width/2,frame.center().y()-height/2,width,height)
    painter.drawImage(r,source)
    return r


def _font(painter, size):
    from PySide6.QtGui import QFont
    f=QFont('DejaVu Sans');f.setPixelSize(max(9,int(size)))
    painter.setFont(f)


def _latex_to_text(value: str) -> str:
    text = str(value or '')
    replacements = {'$':'','\\Delta':'Δ','\\delta':'δ','\\gamma':'γ','\\Gamma':'Γ','\\mu':'μ','\\alpha':'α','\\beta':'β','\\theta':'θ','\\phi':'φ','\\pm':'±','\\AA':'Å','\\,':' ','\\ ':' ','\\_':'_','{':'','}':''}
    for src,dst in replacements.items():
        text=text.replace(src,dst)
    import re
    text=re.sub(r'\\mathrm\s*','',text)
    text=re.sub(r'\\text\s*','',text)
    return ' '.join(text.split())


def _palette_rgb(style, fraction: float) -> np.ndarray:
    palette=lut(style.colormap)
    return palette[int(np.clip(round(fraction*255),0,255))]


def _smart_text_color(rgb) -> str:
    rgb=np.asarray(rgb,dtype=float)[:3]/255.0
    y=0.2126*rgb[0]+0.7152*rgb[1]+0.0722*rgb[2]
    return '#111111' if y>0.58 else '#ffffff'


def _draw_labeled_gradient(painter, rect, style):
    colors=lut(style.colormap)
    if rect.width() >= rect.height():
        im=qimage_rgb(np.broadcast_to(colors[None,:,:],(14,256,3)))
    else:
        im=qimage_rgb(np.ascontiguousarray(colors[::-1,None,:].repeat(14,axis=1)))
    painter.drawImage(rect,im)


def _colorbar(painter, rect, style, lo, hi, unit, title, side, font_size, *, zero_reference=False,
              base_unit=None):
    """Use the SAME colorbar renderer as the live scan preview."""
    draw_colorbar(painter,rect,style,lo,hi,title,unit,position=side,
                  font_px=font_size,zero_reference=zero_reference,base_unit=base_unit)


def _draw_scale_bar(painter, rect, physical_width_m, font_size, color='#111111',
                    position='bottom_right'):
    """Physical bar is automatically ~25% of the scan width, never full width."""
    _draw_gwyddion_scale_bar(painter,rect,physical_width_m,color=color,
                              font_pt=font_size,position=position)


PARAMETER_CORNERS=('top_left','top_right','bottom_left','bottom_right')


def _draw_parameter_box(painter, rect, lines, corner='top_left', font_size=10., color='#ffffff',
                        box=True, avoid_corner=None):
    """v0.0.10: acquisition parameters (bias, setpoint, Δz of each Multipass pass …) written
    inside the image in a chosen corner. A corner shared with the scale bar moves the text
    off the bar (above it for bottom corners, below it for top corners)."""
    from PySide6.QtCore import QRectF, QPointF, Qt
    from PySide6.QtGui import QColor, QFontMetricsF, QFont
    lines=[str(x) for x in (lines or []) if str(x).strip()]
    if not lines or rect.width()<20 or rect.height()<20:return
    corner=corner if corner in PARAMETER_CORNERS else 'top_left'
    painter.save()
    font=QFont('DejaVu Sans')
    # Small enough to never cover the scan: ≤ 1/14 of the image height per line.
    pixel=max(7.,min(float(font_size)*0.92,rect.height()/max(8.,len(lines)*2.8+2)))
    font.setPixelSize(int(round(pixel)))
    painter.setFont(font)
    metrics=QFontMetricsF(font)
    pad=max(3.,pixel*0.45)
    line_h=metrics.height()*1.08
    width=max(metrics.horizontalAdvance(line) for line in lines)+2*pad
    height=line_h*len(lines)+2*pad-(line_h-metrics.height())
    width=min(width,rect.width()-2*pad)
    margin=max(3.,rect.width()*0.02)
    left=rect.left()+margin if corner.endswith('left') else rect.right()-margin-width
    top=rect.top()+margin if corner.startswith('top') else rect.bottom()-margin-height
    if avoid_corner==corner:
        shift=max(pixel*3.6,rect.height()*0.11)
        top=top+shift if corner.startswith('top') else top-shift
    box_rect=QRectF(left,top,width,height)
    text=QColor(color or '#ffffff')
    if box:
        dark=text.lightnessF()>0.5
        fill=QColor(0,0,0,150) if dark else QColor(255,255,255,190)
        painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(fill)
        painter.drawRoundedRect(box_rect,pad*0.8,pad*0.8)
    painter.setBrush(Qt.BrushStyle.NoBrush);painter.setPen(text)
    align=int(Qt.AlignmentFlag.AlignLeft if corner.endswith('left') else Qt.AlignmentFlag.AlignRight)
    for k,line in enumerate(lines):
        r=QRectF(left+pad,top+pad+k*line_h,width-2*pad,metrics.height())
        painter.drawText(r,align|int(Qt.AlignmentFlag.AlignVCenter),
                         metrics.elidedText(line,Qt.TextElideMode.ElideRight,r.width()))
    painter.restore()


def _draw_lattice(painter, rect, info):
    from PySide6.QtCore import QPointF, Qt, QRectF
    from PySide6.QtGui import QPen, QColor, QPolygonF
    basis=np.asarray(info['basis_local_nm'],dtype=float)
    if basis.shape!=(2,2):return
    width_nm,height_nm=info['roi_geometry']['size_nm']
    anchor=QPointF(rect.center())
    sx=rect.width()/width_nm;sy=rect.height()/height_nm
    colors=list(info.get('vector_colors',('#16d8f5','#fbb748')))
    vec_pixels=[]
    painter.save()
    for i in range(2):
        dx=float(basis[0,i])*sx;dy=-float(basis[1,i])*sy
        end=QPointF(anchor.x()+dx,anchor.y()+dy)
        vec_pixels.append((dx,dy))
        col=QColor(colors[i]);painter.setPen(QPen(col,max(1.5,rect.width()*.005)))
        painter.drawLine(anchor,end)
        angle=math.atan2(dy,dx);head=max(6.,rect.width()*.018)
        poly=QPolygonF([end,QPointF(end.x()-head*math.cos(angle-.45),end.y()-head*math.sin(angle-.45)),QPointF(end.x()-head*math.cos(angle+.45),end.y()-head*math.sin(angle+.45))])
        painter.setBrush(col);painter.drawPolygon(poly);painter.setBrush(Qt.BrushStyle.NoBrush)
    p0,p1=vec_pixels
    theta0=math.degrees(math.atan2(-p0[1],p0[0])); theta1=math.degrees(math.atan2(-p1[1],p1[0]))
    delta=(theta1-theta0)%360
    if delta>180: theta0,theta1=theta1,theta0; delta=360-delta
    radius=max(7,min(np.linalg.norm(p0),np.linalg.norm(p1))*.35)
    painter.setPen(QPen(QColor('#ffffff'),max(1.,rect.width()*.003)))
    arc=QRectF(anchor.x()-radius,anchor.y()-radius,2*radius,2*radius)
    painter.drawArc(arc,round(theta0*16),round(delta*16))
    _font(painter,max(10,rect.width()*.029))
    corner=info.get('vector_legend_corner','top_left')
    a_len=10*np.linalg.norm(basis[:,0]); b_len=10*np.linalg.norm(basis[:,1]); gamma=float(info['gamma_deg'])
    rows=[(f'a = {a_len:.2f} Å',colors[0]),(f'b = {b_len:.2f} Å',colors[1]),
          (f'γ = {gamma:.1f}°','#ffffff')]
    _font(painter,max(10,rect.width()*.029))
    from PySide6.QtGui import QFontMetricsF
    metrics=QFontMetricsF(painter.font())
    line_h=metrics.height()*1.20
    for i,(value,color) in enumerate(rows):
        line_w=metrics.horizontalAdvance(value)+4
        x=(rect.left()+6 if corner.endswith('left') else rect.right()-line_w-6)
        y=(rect.top()+6+i*line_h if corner.startswith('top')
           else rect.bottom()-6-(3-i)*line_h)
        painter.setPen(QColor(color))
        painter.drawText(QRectF(x,y,line_w,line_h),Qt.AlignmentFlag.AlignLeft,value)
    painter.restore()


def _manifest_style(info):
    """Display style stored by the lattice tool (v0.8), so Export… shows the same colours."""
    try:
        from .script_figures import style_from_dict
        return style_from_dict(info.get('display_style'))
    except Exception:
        return None


ARRANGEMENTS=('row','triangle','inverted_triangle','grid')
MAX_PANELS=12


def grid_shape(n, columns=0):
    """(columns, rows) of a grid of ``n`` panels; ``columns=0`` picks a near-square grid."""
    import math
    n=max(1,int(n))
    columns=int(columns or 0)
    if columns<=0:columns=math.ceil(math.sqrt(n))
    columns=max(1,min(columns,n))
    return columns,math.ceil(n/columns)


def layout_cells(n, width, height, margin, gap, arrangement='row', columns=0):
    """Panel rectangles (x, y, w, h) in page pixels.

    * 1 or 2 panels, or ``row``: side by side.
    * ``triangle`` (3 panels): one centred on top, two below  ▲
    * ``inverted_triangle`` (3 panels): two on top, one centred below  ▼
    * ``grid`` (v0.0.5, any number of panels): ``columns`` per row (0 = automatic); an incomplete
      last row is centred.
    Panel order: top → bottom, left → right.
    """
    uw=width-2*margin;uh=height-2*margin
    if arrangement=='grid':
        cols,rows=grid_shape(n,columns)
        cw=(uw-gap*(cols-1))/cols;rh=(uh-gap*(rows-1))/rows
        cells=[]
        for i in range(n):
            r,c=divmod(i,cols)
            in_row=min(cols,n-r*cols)
            offset=(uw-(in_row*cw+(in_row-1)*gap))/2
            cells.append((margin+offset+c*(cw+gap),margin+r*(rh+gap),cw,rh))
        return cells
    if n==3 and arrangement in ('triangle','inverted_triangle'):
        cw=(uw-gap)/2;rh=(uh-gap)/2
        centre=(margin+(uw-cw)/2)
        top_y=margin;bottom_y=margin+rh+gap
        if arrangement=='triangle':
            return [(centre,top_y,cw,rh),(margin,bottom_y,cw,rh),(margin+cw+gap,bottom_y,cw,rh)]
        return [(margin,top_y,cw,rh),(margin+cw+gap,top_y,cw,rh),(centre,bottom_y,cw,rh)]
    cw=(uw-gap*(n-1))/n
    return [(margin+i*(cw+gap),margin,cw,uh) for i in range(n)]


def _panel_scan(scan, spec, cache):
    """The scan a panel reads: the active one, or another file named by ``spec['scan_path']``."""
    other=spec.get('scan_path')
    if not other or (scan is not None and Path(other).resolve()==Path(scan.path).resolve()):
        return scan
    key=str(Path(other).resolve())
    if key not in cache:
        from .io import read_scan
        cache[key]=read_scan(key)
    return cache[key]


def export_publication(scan, panels, destination, preset, *, plot_config=None, transparent=False,
                       arrangement='row', panel_letters=None, columns=0):
    """``transparent`` leaves the page background unpainted (PNG alpha, PDF and SVG without a
    white rectangle); JPEG has no alpha and stays white."""
    from PySide6.QtCore import QRectF, QSizeF, QSize, QRect, Qt
    from PySide6.QtGui import QPainter, QImage, QColor, QPdfWriter, QPageSize
    preset=validate_export(preset)
    dest=unique_target(Path(destination))
    suffix=dest.suffix.lower()
    if suffix not in ('.png','.jpg','.jpeg','.pdf','.svg'):
        raise ValueError('Publication layout supports PNG, JPG, PDF and SVG')
    if not 1<=len(panels)<=MAX_PANELS:raise ValueError(f'Select 1 to {MAX_PANELS} publication panels')
    if arrangement not in ARRANGEMENTS:raise ValueError(f'Unknown arrangement {arrangement!r}')
    if len(panels)>3 and arrangement!='grid':arrangement='grid'   # row/triangle exist for up to 3 images
    main_scan=scan
    scan_cache={}
    # Panels of other scans (v0.0.5) are read once, before any painting starts.
    panel_scans=[_panel_scan(main_scan,spec,scan_cache) for spec in panels]
    if panel_letters is None:panel_letters=len(panels)>1
    dest.parent.mkdir(parents=True,exist_ok=True)
    dpi=int(preset['dpi'])
    w=max(96,round(preset['width_mm']/25.4*dpi));h=max(96,round(preset['height_mm']/25.4*dpi))
    def draw(painter):
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing,True)
        margin=dpi/25.4*float(preset['margin_mm']);gap=dpi/25.4*4 if len(panels)>1 else 0
        font_size=dpi/72*float(preset['font_size_pt'])
        cells=layout_cells(len(panels),w,h,margin,gap,arrangement,columns)
        letter_size=font_size*1.35
        letter_strip=letter_size*1.25 if panel_letters and len(panels)>1 else 0.
        side_reserve=max(30, font_size*2.8)
        below_reserve=font_size*2.20
        for i,spec in enumerate(panels):
            scan=panel_scans[i]
            cx,cy,cw,ch=cells[i]
            cell=QRectF(cx,cy+letter_strip,cw,max(24.,ch-letter_strip))
            side=spec.get('colorbar_position','right')
            aspect=1.0
            geometry=None
            base_unit=None
            if spec['kind']=='channel':
                channel=scan.channels[spec['channel']]
                base_unit=channel.unit
                source=np.asarray(channel.get(spec.get('trace','forward')))
                from .processing import apply
                steps=spec.get('steps',[])
                source=apply(source,steps) if steps else source
                geometry=channel.geometry
                aspect=(geometry.size_m[0]/geometry.size_m[1] if geometry.size_m else source.shape[1]/source.shape[0])
                style=spec.get('style',ImageStyle())
                lo,hi=bounds(source,style)
                raw_image=qimage_rgb(render_rgb(source,style))
                info=None
            elif spec['kind']=='lattice':
                info=json.loads(Path(spec['manifest']).read_text(encoding='utf-8'))
                raw_data=Path(info['cropped_scan_npy'])
                if not raw_data.is_file(): raw_data=Path(spec['manifest']).parent/raw_data.name
                source=np.load(raw_data,allow_pickle=False)
                width_nm,height_nm=info['roi_geometry']['size_nm']; aspect=width_nm/height_nm
                base_unit=str(info.get('source_unit','') or '')
                style=spec.get('style') or _manifest_style(info) or ImageStyle()
                lo,hi=bounds(source,style)
                raw_image=qimage_rgb(render_rgb(source,style))
            elif spec['kind']=='array':
                # v0.8: script figures (lattice / molecules) use this exact panel renderer.
                source=np.asarray(spec['data'])
                width_nm,height_nm=map(float,spec['size_nm']);aspect=width_nm/max(1e-12,height_nm)
                base_unit=str(spec.get('base_unit','') or '')
                info=spec.get('lattice')
                style=spec.get('style') or ImageStyle()
                lo,hi=bounds(source,style)
                raw_image=qimage_rgb(render_rgb(source,style))
            else:
                report=_best_report_source(Path(spec['path']))
                if report.suffix.lower()=='.svg':
                    # v32: vector result (lattice, molecules, overlays …) rendered at 2× the
                    # export resolution, so side-by-side panels are as sharp as the originals.
                    from PySide6.QtSvg import QSvgRenderer
                    renderer=QSvgRenderer(str(report))
                    if not renderer.isValid():raise ValueError(f'Cannot read SVG result: {report}')
                    vb=renderer.viewBoxF();aspect=vb.width()/max(1e-9,vb.height()) if vb.height()>0 else 1.
                    target_width=int(min(8000,max(1600,cell.width()*2)))
                    raw_image=QImage(target_width,max(16,int(target_width/max(aspect,1e-9))),QImage.Format.Format_ARGB32)
                    raw_image.fill(QColor(0,0,0,0))
                    _p=QPainter(raw_image);_p.setRenderHint(QPainter.RenderHint.Antialiasing,True)
                    renderer.render(_p);_p.end()
                    if transparent:raw_image=_qimage_key_white(raw_image)
                elif report.suffix.lower() in ('.png','.jpg','.jpeg'):
                    raw_image=QImage(str(report))
                    if raw_image.isNull():raise ValueError(f'Cannot read result image: {report}')
                    if transparent:raw_image=_qimage_key_white(raw_image)
                    aspect=raw_image.width()/max(1.,raw_image.height())
                elif report.suffix.lower()=='.pdf':
                    from PySide6.QtPdf import QPdfDocument
                    doc=QPdfDocument();error=doc.load(str(report))
                    if doc.pageCount()<1:raise ValueError(f'Invalid PDF report: {report} ({error})')
                    page=doc.pagePointSize(0);aspect=page.width()/max(1.,page.height())
                    target_width=int(min(8000,max(1600,cell.width()*2)))
                    size=QSize(target_width,max(400,int(target_width/max(aspect,1e-9))))
                    raw_image=doc.render(0,size);doc.close()
                    if raw_image.isNull():raise ValueError(f'Cannot render PDF result: {report}')
                    if transparent:raw_image=_qimage_key_white(raw_image)
                else:raise ValueError(f'Unsupported result image format: {report.suffix}')
                info=None;lo=0.;hi=1.;style=ImageStyle()
                source_channel=spec.get('colorbar_source') if spec.get('show_colorbar') else None
                if source_channel:
                    if source_channel not in scan.channels:
                        raise ValueError(f'Colourbar reference channel not found: {source_channel}')
                    ref=scan.channels[source_channel]
                    trace=spec.get('trace','forward')
                    if trace not in ref.traces:trace=next(iter(ref.traces))
                    reference=np.asarray(ref.get(trace))
                    from .processing import apply
                    steps=spec.get('colorbar_steps',[])
                    reference=apply(reference,steps) if steps else reference
                    style=spec.get('colorbar_style',ImageStyle(colormap='gray'))
                    lo,hi=bounds(reference,style)
                    spec=dict(spec)
                    base_unit=ref.unit
                    spec['unit']=spec.get('unit') or ref.unit
                    # The report's filename/title is NOT the instrument channel
                    # name. Quantitative gradient labels must use the explicitly
                    # selected source channel, not the graphical overlay title.
                    spec['colorbar_title']=source_channel
            # Identical image allocation for every panel, even when comparing a
            # left/right legend to a below legend or a numerical lattice result.
            # Reserve BOTH a possible vertical label lane and a bottom label lane.
            reserve_side=side in ('right','left') and spec.get('show_colorbar',True)
            fixed_width=max(24.,cell.width()-(side_reserve if reserve_side else 0.))
            fixed_height=max(24.,cell.height()-font_size*0.45-(below_reserve if side=='below' else 0.))
            if side=='left' and reserve_side: frame_x=cell.left()+side_reserve
            else: frame_x=cell.left()
            figure_title=str(spec.get('figure_title','') or '').strip()
            title_strip=font_size*1.7 if figure_title else 0.
            frame=QRectF(frame_x,cell.top()+font_size*0.25+title_strip,fixed_width,max(24.,fixed_height-title_strip))
            image_rect=_draw_image_with_aspect(painter,raw_image,frame,aspect)
            if figure_title:
                painter.save()
                from PySide6.QtGui import QFont
                title_font=QFont('DejaVu Sans');title_font.setPixelSize(max(9,int(font_size*1.15)))
                painter.setFont(title_font);painter.setPen(QColor('#111111'))
                painter.drawText(QRectF(image_rect.left(),image_rect.top()-title_strip,image_rect.width(),title_strip),
                                 Qt.AlignmentFlag.AlignHCenter|Qt.AlignmentFlag.AlignVCenter,_latex_to_text(figure_title))
                painter.restore()
            if letter_strip:
                # Bold journal-style letter a, b, c just above the image's top-left corner.
                painter.save()
                from PySide6.QtGui import QFont
                letter_font=QFont('DejaVu Sans');letter_font.setPixelSize(max(9,int(letter_size)))
                letter_font.setBold(True);painter.setFont(letter_font)
                painter.setPen(QColor('#000000'))
                painter.drawText(QRectF(image_rect.left(),image_rect.top()-letter_strip,
                                        max(letter_size*2,image_rect.width()),letter_strip),
                                 Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,chr(ord('a')+i))
                painter.restore()
            if spec['kind']=='lattice':
                _draw_lattice(painter,image_rect,info)
                if style.scale_bar and spec.get('show_scale_bar',True):_draw_scale_bar(painter,image_rect,info['roi_geometry']['size_nm'][0]*1e-9,font_size,spec.get('scale_bar_color','#111111'),
                              spec.get('scale_bar_position','bottom_right'))
            elif spec['kind']=='array':
                if callable(spec.get('decorate')):
                    painter.save();spec['decorate'](painter,image_rect);painter.restore()
                if info:_draw_lattice(painter,image_rect,info)
                if style.scale_bar and spec.get('show_scale_bar',True):
                    _draw_scale_bar(painter,image_rect,float(spec['size_nm'][0])*1e-9,font_size,
                                    spec.get('scale_bar_color','#111111'),spec.get('scale_bar_position','bottom_right'))
            elif spec['kind']=='channel' and style.scale_bar and spec.get('show_scale_bar',True) and geometry.size_m:
                _draw_scale_bar(painter,image_rect,geometry.size_m[0],font_size,spec.get('scale_bar_color','#111111'),
                              spec.get('scale_bar_position','bottom_right'))
            if spec['kind']=='channel' and spec.get('overlays'):
                _draw_overlays(painter,image_rect,geometry,spec['overlays'])
            box=spec.get('parameter_box') or {}
            if box.get('enabled') and box.get('lines'):
                bar_corner=(spec.get('scale_bar_position','bottom_right')
                            if style.scale_bar and spec.get('show_scale_bar',True) else None)
                _draw_parameter_box(painter,image_rect,box['lines'],box.get('corner','top_left'),font_size,
                                    box.get('color','#ffffff'),bool(box.get('background',True)),bar_corner)
            if spec.get('show_colorbar',True) and side!='none' and (
                    spec['kind']!='report' or spec.get('colorbar_source')):
                _colorbar(painter,image_rect,style,lo,hi,spec.get('unit',''),
                          spec.get('colorbar_title',spec.get('title','')),side,font_size,
                          zero_reference=(display_zero_enabled(spec.get('steps',())) if spec['kind']=='channel'
                                          else bool(spec.get('display_zero',False))),
                          base_unit=base_unit)
    from .export import render_tight
    # v31: page cropped exactly to the drawn content (no empty bands at the
    # top/bottom or on the outer left/right edges); same pixels per mm.
    render_info=render_tight(dest,draw,w,h,dpi,transparent=transparent)
    scan=main_scan
    try:source_fingerprint=fingerprint(scan.path)
    except OSError:source_fingerprint=None
    metadata={'schema_version':1,'source':str(scan.path),'columns':int(columns or 0),'fingerprint':source_fingerprint,'export_preset':preset,'transparent_background':bool(transparent),'tight_crop':render_info,'arrangement':arrangement,'panel_letters':bool(panel_letters),'panels':[{k:(str(v) if isinstance(v,Path) else (v.__dict__ if isinstance(v,ImageStyle) else [getattr(s,'__dict__',s) for s in v] if k=='steps' else v)) for k,v in panel.items() if k not in ('data','decorate')} for panel in panels]}
    dest.with_name(dest.name+'.provenance.json').write_text(json.dumps(metadata,indent=2,default=str)+'\n',encoding='utf-8')
    return dest


def export_numerical_panel(scan, spec, destination, preset):
    from .processing import apply
    from .export import export_scan
    channel=spec['channel'];direction=spec['trace']; steps=spec.get('steps',[])
    raw=scan.channels[channel].get(direction)
    processed=apply(raw,steps) if steps else np.asarray(raw)
    return export_scan(scan,channel,direction,processed,steps,spec.get('style',ImageStyle()),destination,preset)


def export_publication_formats(scan, panels, destination, preset, formats=('pdf',), **kwargs):
    """v33: write the same publication figure in several formats (pdf / png / svg / jpg).

    ``destination`` gives the folder and base name; its own extension is ignored.
    Returns the list of written files.
    """
    base=Path(destination)
    if base.suffix.lower() in ('.pdf','.png','.svg','.jpg','.jpeg'):base=base.with_suffix('')
    wanted=[f.lower().lstrip('.') for f in formats if f.lower().lstrip('.') in ('pdf','png','svg','jpg')]
    if not wanted:raise ValueError('Choose at least one export format (PDF, PNG or SVG)')
    written=[]
    for fmt in dict.fromkeys(wanted):
        written.append(export_publication(scan,panels,Path(str(base)+'.'+fmt),preset,**kwargs))
    return written
