"""One Qt painter for live preview and publication exports (raster data, vector labels)."""
from __future__ import annotations
from .models import Geometry, ImageStyle, preferred_display_unit, display_unit_for
import numpy as np


def qimage_rgb(rgb):
    from PySide6.QtGui import QImage
    arr = np.ascontiguousarray(rgb, dtype=np.uint8)
    ny,nx,_ = arr.shape
    return QImage(arr.data, nx, ny, 3*nx, QImage.Format.Format_RGB888).copy()


def image_rect(rect, geometry: Geometry, has_colorbar=False):
    from PySide6.QtCore import QRectF
    margin = min(rect.width(),rect.height()) * .025
    left, top = rect.left()+margin, rect.top()+margin
    avail_w = max(1., rect.width()-2*margin)
    avail_h = max(1., rect.height()-2*margin-(46 if has_colorbar else 0))
    ny, nx = geometry.shape
    sx, sy = geometry.size_m if geometry.size_m is not None else (float(nx), float(ny))
    aspect = sx/sy
    w = min(avail_w, avail_h*aspect)
    h = w/aspect
    return QRectF(left + (avail_w-w)/2, top + (avail_h-h)/2,w,h)


def nice_length(length):
    """A readable 1/2/5 length near 25% of the scan width (never over 35%).

    Input/output are in the SAME units, normally physical metres.
    E.g. 20 nm wide -> 5 nm bar, not a 20 nm bar.
    """
    length=float(length)
    if not np.isfinite(length) or length <= 0:
        return 0.0
    target=length*0.25
    exponent=int(np.floor(np.log10(target)))
    candidates=[base*10.0**power for power in range(exponent-2,exponent+2)
                for base in (1.,2.,5.)]
    choices=[x for x in candidates if 0 < x <= length*0.35]
    return min(choices,key=lambda x:(abs(np.log(x/target)), -x)) if choices else length*0.25


def _latex_to_text(value: str) -> str:
    text = str(value or '')
    replacements = {
        '$':'', '\\Delta':'Δ', '\\delta':'δ', '\\gamma':'γ', '\\Gamma':'Γ', '\\mu':'μ',
        '\\alpha':'α', '\\beta':'β', '\\theta':'θ', '\\phi':'φ', '\\pm':'±', '\\AA':'Å',
        '\\,':' ', '\\ ':' ', '\\_':'_', '{':'', '}':'',
    }
    for src,dst in replacements.items():
        text=text.replace(src,dst)
    import re
    text=re.sub(r'\\mathrm\s*', '', text)
    text=re.sub(r'\\text\s*', '', text)
    return ' '.join(text.split())


def _text_color_for_rgb(rgb) -> str:
    rgb=np.asarray(rgb,dtype=float)[:3]/255.0
    luminance = 0.2126*rgb[0]+0.7152*rgb[1]+0.0722*rgb[2]
    return '#111111' if luminance > 0.58 else '#ffffff'




def foreground_on_background(background):
    """Readable colour for unfilled legend labels in either UI theme."""
    # No Qt dependencies so this can be tested for custom themes as well.
    token=str(background).strip().lstrip('#')
    if len(token)==3:
        token=''.join(ch*2 for ch in token)
    if len(token)!=6:
        return '#ffffff' if str(background).lower() in ('black','dark') else '#20252a'
    try:
        red,green,blue=(int(token[i:i+2],16)/255 for i in (0,2,4))
    except ValueError:
        return '#20252a'
    brightness=.2126*red+.7152*green+.0722*blue
    return '#ffffff' if brightness<.52 else '#20252a'

def _sample_palette_color(colormap: str, fraction: float) -> np.ndarray:
    from .display import lut
    palette = lut(colormap)
    index = int(np.clip(round(float(fraction)*255),0,255))
    return palette[index]


VALID_SCALE_BAR_POSITIONS=('top_left','top_right','bottom_left','bottom_right')


def _scale_bar_geometry(rect, physical_width_m, position='bottom_right'):
    """Compute bar geometry without Qt, for testability and consistent layouts."""
    if position not in VALID_SCALE_BAR_POSITIONS:
        raise ValueError(f'Unknown scale bar position {position!r}')
    distance=nice_length(physical_width_m)
    width_px=rect.width()*distance/physical_width_m if physical_width_m>0 else 0.0
    left=position.endswith('left')
    top=position.startswith('top')
    margin_x=max(6.0,rect.width()*0.055)
    bar_x=rect.left()+margin_x if left else rect.right()-margin_x-width_px
    return distance,width_px,bar_x,top


def _draw_gwyddion_scale_bar(painter, imgrect, physical_width_m, *,
                              color='#111111', font_pt=10, position='bottom_right'):
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QPen, QFont, QFontMetricsF
    if physical_width_m is None or not np.isfinite(physical_width_m) or physical_width_m<=0:
        return
    distance,pixwidth,start_x,is_top=_scale_bar_geometry(imgrect,physical_width_m,position)
    if distance<=0 or pixwidth<=0:return
    painter.save()
    font=QFont('DejaVu Sans')
    font.setPixelSize(max(9,int(min(float(font_pt),imgrect.width()*0.045,imgrect.height()*0.075))))
    painter.setFont(font)
    metrics=QFontMetricsF(font)
    gap=max(4.0,metrics.height()*0.20)
    vertical_pad=max(metrics.height()*1.9,imgrect.height()*0.085)
    y=imgrect.top()+vertical_pad if is_top else imgrect.bottom()-vertical_pad
    tick=max(5.0,min(10.0,imgrect.height()*0.032))
    line_width=max(1.5,min(3.4,imgrect.width()*0.0037))
    pen=QPen(QColor(color),line_width)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(start_x,y),QPointF(start_x+pixwidth,y))
    painter.drawLine(QPointF(start_x,y-tick/2),QPointF(start_x,y+tick/2))
    painter.drawLine(QPointF(start_x+pixwidth,y-tick/2),QPointF(start_x+pixwidth,y+tick/2))
    if distance < 1e-9: value, unit = distance*1e12, 'pm'
    elif distance < 1e-6: value, unit = distance*1e9, 'nm'
    elif distance < 1e-3: value, unit = distance*1e6, 'μm'
    else: value, unit = distance*1e3, 'mm'
    label=f'{value:g} {unit}'
    label_width=max(pixwidth,metrics.horizontalAdvance(label)+8)
    label_width=min(imgrect.width()-4,label_width)
    label_x=max(imgrect.left()+2,min(start_x+(pixwidth-label_width)/2,imgrect.right()-label_width-2))
    label_y=y+gap+tick/2 if is_top else y-gap-tick/2-metrics.height()
    painter.drawText(QRectF(label_x,label_y,label_width,metrics.height()+2),
                     Qt.AlignmentFlag.AlignHCenter|Qt.AlignmentFlag.AlignVCenter,label)
    painter.restore()


def _draw_gradient(painter, box, colormap, vertical=False):
    from .display import lut
    colors=lut(colormap)
    if vertical:
        rgb=np.ascontiguousarray(colors[::-1,None,:].repeat(12,axis=1))
    else:
        rgb=np.broadcast_to(colors[None,:,:],(12,256,3))
    painter.drawImage(box,qimage_rgb(rgb))


def _fit_font_to_width(painter, label, max_width, initial_px):
    from PySide6.QtGui import QFontMetricsF
    size=max(8,int(initial_px))
    font=painter.font()
    font.setPixelSize(size)
    while size>8 and QFontMetricsF(font).horizontalAdvance(label) > max_width:
        size-=1; font.setPixelSize(size)
    painter.setFont(font)


def draw_colorbar(painter, imgrect, style, lo, hi, name, unit,
                  *, position='below', font_px=12, zero_reference=False, outside_text_color='#222222',
                  base_unit=None):
    """Title inside the LUT; extrema outside it but in the SAME raster footprint.

    ``unit`` is the label the user asked for; ``base_unit`` the unit of the numbers (the channel
    unit). Equal or empty: automatic SI scaling. Different (nm, Å, mV...): converted."""
    from PySide6.QtCore import Qt, QRectF
    from PySide6.QtGui import QColor, QFontMetricsF, QFont
    if position=='none':return
    font_px=max(9,int(font_px))
    painter.save()
    font=QFont('DejaVu Sans');font.setPixelSize(font_px);painter.setFont(font)
    display_lo,display_hi=(0.0,float(hi)-float(lo)) if zero_reference else (lo,hi)
    text_unit,mult=display_unit_for(unit,base_unit if base_unit is not None else unit,
                                    np.asarray([display_lo,display_hi]))
    low=f'{display_lo*mult:.3g}'
    high=f'{display_hi*mult:.3g}'
    if has_math(name):
        # Keep $…$ for real typesetting; plain unit text in brackets.
        label=f'{name} [{_latex_to_text(text_unit)}]' if text_unit else str(name)
    else:
        label=_latex_to_text(name)
        label=f'{label} [{_latex_to_text(text_unit)}]' if text_unit else label
    metrics=QFontMetricsF(font)
    if position=='below':
        bar_height=max(17.,font_px*1.48)  # slightly thicker than v4
        # The combined LEFT VALUE + GRADIENT + RIGHT VALUE spans exactly image width.
        overall=QRectF(imgrect.left(),imgrect.bottom()+max(4.,font_px*.28),imgrect.width(),bar_height)
        number_padding=font_px*.55
        left_label=metrics.horizontalAdvance(low)+number_padding
        right_label=metrics.horizontalAdvance(high)+number_padding
        # Keep at least 40% of image width for the gradient on narrow scans.
        scale=min(1.0,overall.width()*.28/max(left_label,right_label,1.0))
        left_label*=scale;right_label*=scale
        gradient=QRectF(overall.left()+left_label,overall.top(),
                        max(1.,overall.width()-left_label-right_label),overall.height())
        _draw_gradient(painter,gradient,style.colormap)
        painter.setPen(QColor(outside_text_color))
        painter.drawText(QRectF(overall.left(),overall.top(),left_label-2,overall.height()),
                         Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,low)
        painter.drawText(QRectF(gradient.right()+2,overall.top(),right_label-2,overall.height()),
                         Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignRight,high)
        draw_label(painter,gradient,label,_text_color_for_rgb(_sample_palette_color(style.colormap,.5)),font_px)
    elif position in ('right','left'):
        gap=max(5.,font_px*.40)
        thick=max(18.,font_px*1.48)
        x=imgrect.right()+gap if position=='right' else imgrect.left()-gap-thick
        top_h=max(14.,font_px*1.4); bottom_h=top_h
        bar=QRectF(x,imgrect.top()+top_h,thick,max(1.,imgrect.height()-top_h-bottom_h))
        _draw_gradient(painter,bar,style.colormap,vertical=True)
        painter.setPen(QColor(outside_text_color))
        painter.drawText(QRectF(x-32,imgrect.top(),thick+64,top_h),Qt.AlignmentFlag.AlignCenter,high)
        painter.drawText(QRectF(x-32,bar.bottom(),thick+64,bottom_h),Qt.AlignmentFlag.AlignCenter,low)
        painter.save(); painter.translate(bar.center());painter.rotate(-90 if position=='right' else 90)
        draw_label(painter,QRectF(-bar.height()/2,-thick/2,bar.height(),thick),label,
                   _text_color_for_rgb(_sample_palette_color(style.colormap,.5)),font_px)
        painter.restore()
    else:
        painter.restore();raise ValueError(f'Unknown colourbar position {position!r}')
    painter.restore()


def paint_frame(painter, rgb_image, bounds, name, unit, geometry, style,
                canvas, overlays=(), *, background='#ffffff', font_pt=10, scale_bar_color=None,
                scale_bar_position='bottom_right', display_zero=False):
    from PySide6.QtCore import Qt, QRectF, QPointF
    from PySide6.QtGui import QColor, QFont, QPen
    painter.save()
    if str(background).lower() not in ('transparent','none',''):
        painter.fillRect(canvas, QColor(background))
    imgrect = image_rect(canvas, geometry, style.colorbar)
    painter.setRenderHint(painter.RenderHint.SmoothPixmapTransform, True)
    painter.drawImage(imgrect, rgb_image)
    painter.setRenderHint(painter.RenderHint.Antialiasing, True)
    font = QFont('DejaVu Sans')
    font.setPointSizeF(font_pt)
    painter.setFont(font)
    if style.scale_bar and geometry.size_m is not None:
        from .plot_settings import default_scale_bar_color
        by_channel = default_scale_bar_color(name)   # v34: Z black; excitation / torsional white
        color = scale_bar_color or (by_channel if by_channel != '#111111' else
                                    ('#ffffff' if background.lower() in ('#171b21','#222831','#202b36') else '#111111'))
        _draw_gwyddion_scale_bar(painter, imgrect, geometry.size_m[0],
                                  color=color, font_pt=font_pt, position=scale_bar_position)
    if overlays:
        _draw_overlays(painter, imgrect, geometry, overlays)
    if style.colorbar:
        # The numbers sit OUTSIDE the gradient; the current surface theme,
        # rather than the selected data palette, owns their foreground.
        outside=foreground_on_background(background)
        draw_colorbar(painter,imgrect,style,bounds[0],bounds[1],name,unit,
                      position='below',font_px=max(10,int(font_pt*1.25)),
                      zero_reference=display_zero,outside_text_color=outside)
    painter.restore()
    return imgrect


def _draw_overlays(painter, rect, geometry, overlays):
    from PySide6.QtGui import QPen, QColor
    from PySide6.QtCore import QPointF, QRectF
    for o in overlays:
        try:
            color = QColor(o.get('color','#ffda55'))
            width=float(o.get('width',2))
            if o.get('width_mode')=='scan':
                width=max(1.,width*rect.width()/500.)
            painter.setPen(QPen(color,max(1.,width)))
            t = o['type']
            pts = o.get('points_px',[])
            points = [QPointF(rect.left()+(col+.5)/geometry.shape[1]*rect.width(),
                              rect.top()+(row+.5)/geometry.shape[0]*rect.height()) for col,row in pts]
            if t == 'line' and len(points) >= 2:
                for a, b in zip(points, points[1:]):
                    painter.drawLine(a, b)
            elif t == 'rectangle' and len(points) == 2:
                painter.drawRect(QRectF(points[0],points[1]).normalized())
            elif t == 'point' and points:
                painter.drawEllipse(points[0],4,4)
            elif t == 'polygon' and len(points)>=3:
                for a,b in zip(points,points[1:]+points[:1]):
                    painter.drawLine(a,b)
        except (KeyError, TypeError, ValueError):
            continue


# ---------------------------------------------------------------------------
# v31 — real LaTeX-style titles ($V_{exc}$, $\\Delta f$, $\\mathrm{d}I/\\mathrm{d}V$ …)
# ---------------------------------------------------------------------------
def has_math(text) -> bool:
    t=str(text or '')
    return t.count('$')>=2 and t.count('$')%2==0


_MATH_CACHE={}


def math_text_path(text, font_px):
    """Vector QPainterPath of ``text`` typeset with Matplotlib mathtext.

    Real subscripts/superscripts, Greek letters, \\mathrm, fractions … exactly like
    Matplotlib plots.  Stays vector in PDF/SVG.  Returns (path, QRectF bounds) or
    None when the expression cannot be parsed.
    """
    from PySide6.QtGui import QPainterPath
    key=(str(text),round(float(font_px),2))
    if key in _MATH_CACHE:return _MATH_CACHE[key]
    try:
        from matplotlib.textpath import TextPath
        from matplotlib.font_manager import FontProperties
        from matplotlib.path import Path as MPath
        tp=TextPath((0,0),str(text),size=float(font_px),prop=FontProperties(family='DejaVu Sans'))
    except Exception:
        _MATH_CACHE[key]=None;return None
    path=QPainterPath()
    for verts,code in tp.iter_segments(curves=True,simplify=False):
        v=list(verts)
        if code==MPath.MOVETO:path.moveTo(v[0],-v[1])
        elif code==MPath.LINETO:path.lineTo(v[0],-v[1])
        elif code==MPath.CURVE3:path.quadTo(v[0],-v[1],v[2],-v[3])
        elif code==MPath.CURVE4:path.cubicTo(v[0],-v[1],v[2],-v[3],v[4],-v[5])
        elif code==MPath.CLOSEPOLY:path.closeSubpath()
    result=(path,path.boundingRect())
    _MATH_CACHE[key]=result
    return result


def draw_label(painter, rect, text, color, font_px, *, fit=True):
    """Centre ``text`` in ``rect``; math ($…$) is typeset, plain text uses the font."""
    from PySide6.QtCore import Qt, QRectF
    from PySide6.QtGui import QColor
    if has_math(text):
        got=math_text_path(text,font_px)
        if got is not None:
            path,b=got
            scale=1.
            if fit and b.width()>0:scale=min(1.,max(.3,(rect.width()-4)/b.width()))
            if fit and b.height()>0:scale=min(scale,max(.3,(rect.height()-2)/b.height()))
            painter.save()
            painter.setRenderHint(painter.RenderHint.Antialiasing,True)
            painter.translate(rect.center().x()-(b.center().x())*scale,
                              rect.center().y()-(b.center().y())*scale)
            painter.scale(scale,scale)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.fillPath(path,QColor(color))
            painter.restore()
            return
        text=_latex_to_text(text)
    painter.save()
    if fit:_fit_font_to_width(painter,text,max(4.,rect.width()-6),int(font_px))
    painter.setPen(QColor(color))
    painter.drawText(rect,Qt.AlignmentFlag.AlignCenter,text)
    painter.restore()
