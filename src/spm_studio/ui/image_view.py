"""Direct Qt SPM preview: cursor-centred zoom, pan, ROI and physical readout."""
from __future__ import annotations
import numpy as np
import math
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QPainter, QImage, QPen, QColor
from PySide6.QtWidgets import QWidget, QScrollArea
from ..core.painting import paint_frame, image_rect
from ..core.models import Geometry, ImageStyle, ROI

class ImageView(QWidget):
    cursorChanged = Signal(str)
    cursorPixelChanged = Signal(object)
    activated = Signal()
    roiChanged = Signal(object)
    roiPreview = Signal(object)
    roiEdited = Signal()
    deleteSelectedRequested = Signal()
    roiSelected = Signal(int)     # v0.0.11: a click on a line / region selects it

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(360,300)
        self.image = None
        self.data = None
        self.geometry = None
        self.style = ImageStyle()
        self.bounds = (0.,1.)
        self.channel = ''
        self.unit = ''
        self.zoom = 1.
        self.pan = QPointF(0.,0.)
        self.tool = 'pan'
        self.drag_start = None
        self.drag_current = None
        self._edit = None
        self._press_inside_existing = False
        self.roi = None
        self.extra_rois = []
        self.selected_roi_index = -1
        self.mask_overlay = None
        self.tool_mask_overlay = None
        self.tool_points = []
        self.tool_preview_image = None
        self.tool_preview_roi = None
        self.overlays = []
        self.plot_profile = {}
        self.line_styles = {}   # {points: (colour, name[, exported scan-width factor])}
        self.molecule_overlay = None   # v32: manual molecules {'art','items','selected','opacity'}
        self._result = False
        self.display_zero = False
        # v0.0.10 polylines: Shift+click after a line continues it with a new segment.
        self._last_line_pts = None   # vertices of the line that Shift+click extends
        self._poly_cursor = None     # screen position of the dashed next-segment preview
        self._poly_click = False
        # v0.0.11: every line keeps its colour for its whole life (deleting another line
        # renumbers the names L1, L2 … but never recolours the remaining lines).
        self.line_colors = {}

    def set_scan(self,image:QImage,data,geometry:Geometry,style:ImageStyle,bounds,channel,unit,
                 *,preserve_view=False,display_zero=False):
        self.image = image
        self.data = data
        self.geometry = geometry
        self.style = style
        self.bounds = bounds
        self.channel = channel
        self.unit = unit
        self._result = False
        self.display_zero = bool(display_zero)
        if not preserve_view:
            self.fit()
            self.roi = None
            self.extra_rois.clear()
            self.mask_overlay=None
            self.tool_mask_overlay=None
            self.tool_points=[]
            self.tool_preview_image=None
            self.tool_preview_roi=None
        self.update()

    def clear_scan(self):
        """Discard current displayed data, overlays, and selection after removal."""
        self.image=None
        self.data=None
        self.geometry=None
        self.channel=''
        self.unit=''
        self.bounds=(0.,1.)
        self.roi=None
        self.extra_rois.clear()
        self.mask_overlay=None
        self.tool_mask_overlay=None
        self.tool_points=[]
        self.tool_preview_image=None
        self.tool_preview_roi=None
        self.overlays=[]
        self.drag_start=self.drag_current=self._edit=None
        self._result=False
        self.display_zero=False
        self.fit()

    def show_result(self,path):
        image = QImage(str(path))
        if image.isNull():
            raise ValueError('Cannot show result image in the central viewer')
        self.image = image
        self.geometry = Geometry((image.height(),image.width()))
        self.channel = str(path.name)
        self.data = None
        self.style = ImageStyle(scale_bar=False,colorbar=False)
        self.overlays = []
        self.tool_mask_overlay = None
        self.tool_points=[]
        self.tool_preview_image=None
        self.tool_preview_roi=None
        self._result = True
        self.display_zero = False
        self.fit()

    def fit(self):
        self.zoom=1.
        self.pan=QPointF(0,0)
        self.update()

    def set_roi_tool(self,tool):
        self.tool = tool
        self.drag_start = None
        self.drag_current = None
        self._edit = None
        self._poly_cursor = None
        self.update()

    # ------------------------------------------------------------ polylines (v0.0.10)
    def _extendable_line(self):
        """(origin, index, roi) of the line Shift+click continues, or ``None``."""
        if self.tool!='line' or self.geometry is None:
            return None
        target=self._last_line_pts
        candidates=([('main',-1,self.roi)] if self.roi is not None else [])+ \
                   [('extra',i,r) for i,r in reversed(list(enumerate(self.extra_rois)))]
        lines=[c for c in candidates if c[2].kind=='line']
        if target is not None:
            for c in lines:
                if tuple(map(tuple,c[2].points_px))==target:
                    return c
        return lines[0] if lines else None

    def _poly_target(self,position,roi,snap=False):
        """Screen position of the next vertex; Ctrl snaps the new segment to 15° steps."""
        if not snap:
            return position
        import math
        last=self._to_screen(roi.points_px[-1])
        dx,dy=position.x()-last.x(),position.y()-last.y()
        length=math.hypot(dx,dy)
        if length<1e-9:
            return position
        angle=round(math.atan2(dy,dx)/math.radians(15))*math.radians(15)
        return QPointF(last.x()+length*math.cos(angle),last.y()+length*math.sin(angle))

    @staticmethod
    def segment_angles(points):
        """(absolute angle of the last segment, turn from the previous one) in degrees.

        Absolute: 0° = to the right, counter-clockwise positive (image Y points down).
        """
        import math
        if len(points)<2:
            return None,None
        (x0,y0),(x1,y1)=points[-2],points[-1]
        absolute=math.degrees(math.atan2(-(y1-y0),x1-x0))
        if len(points)<3:
            return absolute,None
        (xa,ya)=points[-3]
        before=math.degrees(math.atan2(-(y0-ya),x0-xa))
        turn=(absolute-before+180)%360-180
        return absolute,turn

    # ------------------------------------------------------------ line identity (v0.0.11)
    @staticmethod
    def line_key(roi):
        return tuple(map(tuple,roi.points_px))

    def all_rois(self):
        return list(self.extra_rois)+([self.roi] if self.roi is not None else [])

    def line_color_of(self,roi):
        """Persistent colour of a line: assigned once (first palette colour not in use)."""
        from ..core.multi_profiles import line_color,LINE_COLORS
        key=self.line_key(roi)
        style=self.line_styles.get(key)
        if style:
            return style[0]
        if key not in self.line_colors:
            present={self.line_key(r) for r in self.all_rois() if r.kind=='line'}
            used={c for k,c in self.line_colors.items() if k in present}
            used|={s[0] for k,s in self.line_styles.items() if k in present}
            colour=next((line_color(i) for i in range(len(LINE_COLORS)) if line_color(i) not in used),
                        line_color(len(present)))
            self.line_colors[key]=colour
        return self.line_colors[key]

    def line_appearance(self):
        """[(roi index, colour, name)] for every line, numbered L1, L2 … in drawing order."""
        out=[];n=0
        for i,roi in enumerate(self.all_rois()):
            if roi.kind!='line':continue
            style=self.line_styles.get(self.line_key(roi))
            name=style[1] if style else f'L{n+1}'
            out.append((i,self.line_color_of(roi),name))
            n+=1
        return out

    def forget_roi(self,roi):
        """Remove a line's colour / style when it is deleted."""
        key=self.line_key(roi)
        self.line_colors.pop(key,None)
        self.line_styles.pop(key,None)
        if self._last_line_pts==key:
            self._last_line_pts=None

    def renumber_lines(self):
        """Default names (L1, L2 …) follow the drawing order again; custom names and every
        colour are kept."""
        import re
        n=0
        for roi in self.all_rois():
            if roi.kind!='line':continue
            n+=1
            key=self.line_key(roi)
            style=self.line_styles.get(key)
            if style and re.fullmatch(r'L\d+',str(style[1])):
                self.line_styles[key]=(style[0],f'L{n}')+tuple(style[2:])

    def roi_at(self,position,tolerance=7.0):
        """Index (in extra_rois + [roi]) of the line / region / point under the cursor."""
        if self.geometry is None:
            return None
        best=None
        for i,roi in enumerate(self.all_rois()):
            pts=[self._to_screen(p) for p in roi.points_px]
            if roi.kind=='point':
                d=math.hypot(pts[0].x()-position.x(),pts[0].y()-position.y())
            elif roi.kind=='rectangle' and len(pts)==2:
                (x0,y0),(x1,y1)=(pts[0].x(),pts[0].y()),(pts[1].x(),pts[1].y())
                c=[(x0,y0),(x1,y0),(x1,y1),(x0,y1),(x0,y0)]
                d=min(_segment_distance(position,a,b) for a,b in zip(c,c[1:]))
            else:
                d=min((_segment_distance(position,(a.x(),a.y()),(b.x(),b.y())) for a,b in zip(pts,pts[1:])),
                      default=1e9)
            if d<=tolerance and (best is None or d<best[0]):
                best=(d,i)
        return None if best is None else best[1]

    def _select_at(self,position):
        index=self.roi_at(position)
        if index is not None:
            self.selected_roi_index=index
            self.roiSelected.emit(index)
            self.update()
        return index

    def _replace_line(self,origin,index,old,new):
        if origin=='main':self.roi=new
        else:self.extra_rois[index]=new
        key_old=tuple(map(tuple,old.points_px));key_new=tuple(map(tuple,new.points_px))
        if key_old in self.line_styles:
            self.line_styles[key_new]=self.line_styles.pop(key_old)
        if key_old in self.line_colors:
            self.line_colors[key_new]=self.line_colors.pop(key_old)
        if self._last_line_pts==key_old or self._last_line_pts is None:
            self._last_line_pts=key_new

    def extend_line(self,point,origin=None,index=None):
        """Append a vertex ``(col,row)`` to the current line (programmatic Shift+click)."""
        found=self._extendable_line() if origin is None else \
              (origin,index,self.roi if origin=='main' else self.extra_rois[index])
        if found is None:
            return None
        origin,index,roi=found
        last=roi.points_px[-1]
        if abs(point[0]-last[0])+abs(point[1]-last[1])<.5:
            return None
        new=ROI('line',tuple(map(tuple,roi.points_px))+(tuple(map(float,point)),))
        self._last_line_pts=tuple(map(tuple,roi.points_px))
        self._replace_line(origin,index,roi,new)
        self._last_line_pts=tuple(map(tuple,new.points_px))
        self.roiEdited.emit()
        self.update()
        return new

    def _base_rect(self):
        if self.geometry is None:
            return QRectF()
        return image_rect(QRectF(self.rect()),self.geometry,
                          self.style.colorbar and not self._result)

    def _display_rect(self):
        r = self._base_rect()
        c = self.rect().center()
        center = QPointF(c.x(),c.y())
        origin = center + self.pan
        return QRectF(origin.x()+(r.left()-center.x())*self.zoom,
                      origin.y()+(r.top()-center.y())*self.zoom,
                      r.width()*self.zoom,r.height()*self.zoom)

    def _to_pixel(self,position,clamp=False):
        r = self._display_rect()
        if r.isEmpty() or (not clamp and not r.contains(position)):
            return None
        col = (position.x()-r.left())/r.width()*self.geometry.shape[1]-.5
        row = (position.y()-r.top())/r.height()*self.geometry.shape[0]-.5
        if clamp:
            col = max(0.,min(self.geometry.shape[1]-1.,col))
            row = max(0.,min(self.geometry.shape[0]-1.,row))
        return col,row

    def _to_screen(self,point):
        r=self._display_rect()
        return QPointF(r.left()+(point[0]+.5)*r.width()/self.geometry.shape[1],
                       r.top()+(point[1]+.5)*r.height()/self.geometry.shape[0])

    def _near_handle(self,position):
        """Return the precise endpoint/edge selected; never move a whole ROI."""
        if self.tool not in ('line','rectangle','point'):
            return None
        candidates=[]
        candidates.extend(('extra',i,r) for i,r in enumerate(self.extra_rois) if r.kind==self.tool)
        if self.roi is not None and self.roi.kind==self.tool:
            candidates.append(('main',-1,self.roi))
        nearest=None;best=13.0
        for origin,index,roi in candidates:
            p0=self._to_screen(roi.points_px[0])
            p1=self._to_screen(roi.points_px[1]) if len(roi.points_px)>1 else p0
            if roi.kind in ('line','point'):
                handles=[('p0',p0)] if roi.kind=='point' else \
                        [(f'p{k}',self._to_screen(pt)) for k,pt in enumerate(roi.points_px)]
            else:
                l,r=sorted((p0.x(),p1.x()));t,b=sorted((p0.y(),p1.y()))
                handles=[('left',QPointF(l,(t+b)/2)),('right',QPointF(r,(t+b)/2)),
                         ('top',QPointF((l+r)/2,t)),('bottom',QPointF((l+r)/2,b)),
                         ('tl',QPointF(l,t)),('tr',QPointF(r,t)),
                         ('bl',QPointF(l,b)),('br',QPointF(r,b))]
            for handle,pos in handles:
                distance=(position.x()-pos.x())**2+(position.y()-pos.y())**2
                if distance<best*best:
                    best=distance**.5;nearest=(origin,index,handle)
        return nearest

    def _edit_to(self,position):
        if self._edit is None:return
        origin,index,handle=self._edit
        roi=self.roi if origin=='main' else self.extra_rois[index]
        point=self._to_pixel(position,clamp=True)
        if point is None:return
        if roi.kind=='point':
            edited=ROI('point',(point,))
            if origin=='main':self.roi=edited
            else:self.extra_rois[index]=edited
            self.roiEdited.emit()
            self.update()
            return
        if roi.kind=='line':
            vertices=[tuple(p) for p in roi.points_px]
            k=int(handle[1:]) if handle.startswith('p') and handle[1:].isdigit() else -1
            if 0<=k<len(vertices):
                vertices[k]=tuple(point)
            edited=ROI('line',tuple(vertices))
            self._replace_line(origin,index,roi,edited)
            self._last_line_pts=tuple(map(tuple,edited.points_px))
            self.roiEdited.emit()
            self.update()
            return
        (x0,y0),(x1,y1)=roi.points_px
        if handle=='p0':x0,y0=point
        elif handle=='p1':x1,y1=point
        else:
            left,right=sorted((x0,x1));top,bottom=sorted((y0,y1))
            if handle in ('left','tl','bl'):left=min(point[0],right)
            if handle in ('right','tr','br'):right=max(point[0],left)
            if handle in ('top','tl','tr'):top=min(point[1],bottom)
            if handle in ('bottom','bl','br'):bottom=max(point[1],top)
            x0,y0,x1,y1=left,top,right,bottom
        edited=ROI(roi.kind,((x0,y0),(x1,y1)))
        if origin=='main':self.roi=edited
        else:self.extra_rois[index]=edited
        self.roiEdited.emit()
        self.update()

    def paintEvent(self,event):
        painter=QPainter(self)
        from spm_studio.shared.appearance import colors
        ui=colors(self)
        painter.fillRect(self.rect(),QColor(ui['background']))
        if self.image is None:
            painter.setPen(QColor(ui['muted']))
            painter.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,'Open an SXM or GWY scan\nCtrl+O',)
            painter.end()
            return
        r=self._display_rect()
        painter.setClipRect(self.rect())
        if self._result:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,True)
            painter.drawImage(r,self.image)
        else:
            # Shared scientific drawing code and style between preview/export.
            painter.save()
            origin=self.rect().center()
            center=QPointF(origin.x(),origin.y())
            painter.translate(center+self.pan)
            painter.scale(self.zoom,self.zoom)
            painter.translate(-center)
            paint_frame(painter,self.image,self.bounds,self.channel,self.unit,self.geometry,
                        self.style,QRectF(self.rect()),self.overlays,
                        background=ui['background'],font_pt=self.plot_profile.get('label_size',9),
                        display_zero=self.display_zero)
            painter.restore()
        if self.mask_overlay is not None and not self._result:
            painter.drawImage(r,self.mask_overlay)
        if self.tool_mask_overlay is not None and not self._result:
            painter.drawImage(r,self.tool_mask_overlay)
        if self.tool_preview_image is not None and self.tool_preview_roi is not None and not self._result:
            from ..core.interactive_tools import roi_slice
            ys,xs=roi_slice(self.geometry.shape,self.tool_preview_roi)
            p0=QPointF(r.left()+xs.start/self.geometry.shape[1]*r.width(),
                       r.top()+ys.start/self.geometry.shape[0]*r.height())
            p1=QPointF(r.left()+xs.stop/self.geometry.shape[1]*r.width(),
                       r.top()+ys.stop/self.geometry.shape[0]*r.height())
            painter.drawImage(QRectF(p0,p1),self.tool_preview_image)
        if self.tool_points and self.geometry is not None and not self._result:
            painter.save()
            painter.setPen(QPen(QColor('#ffcf4b'),2))
            for i,(x,y) in enumerate(self.tool_points):
                p=self._to_screen((x,y))
                painter.drawEllipse(p,5,5)
                painter.drawText(QPointF(p.x()+7,p.y()-5),str(i+1))
            painter.restore()
        mo=self.molecule_overlay
        if mo and mo.get('art') is not None and self.geometry is not None and not self._result:
            ny,nx=self.geometry.shape
            kx,ky=r.width()/nx,r.height()/ny
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,True)
            for idx,(c,rr,ang,wpx,hpx) in enumerate(mo.get('items',[])):
                painter.save()
                painter.translate(r.left()+(c+.5)*kx,r.top()+(rr+.5)*ky)
                painter.rotate(-ang)
                target=QRectF(-wpx*kx/2,-hpx*ky/2,wpx*kx,hpx*ky)
                painter.setOpacity(float(mo.get('opacity',1.)))
                painter.drawImage(target,mo['art'])
                painter.setOpacity(1.)
                if idx==mo.get('selected'):
                    painter.setPen(QPen(QColor('#00e5ff'),2,Qt.PenStyle.DashLine))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(target)
                painter.restore()
            painter.restore()
        appearance={i:(colour,name) for i,colour,name in self.line_appearance()}
        for roi_index,roi in enumerate(self.extra_rois + ([self.roi] if self.roi is not None else [])):
            painter.save()
            painter.setPen(QPen(QColor('#ffffff') if roi_index==self.selected_roi_index else QColor('#ffda55'),2,Qt.PenStyle.DashLine))
            if roi.kind=='line':
                # v32: every line has its own colour (and name once named in Line profiles)
                line_style=self.line_styles.get(tuple(map(tuple,roi.points_px)))
                colour,name=appearance[roi_index]
                width=(line_style[2] if line_style and len(line_style)>2 else 2)
                if roi_index==self.selected_roi_index:
                    # selected line: white halo under its own colour (the colour never changes)
                    painter.setPen(QPen(QColor(255,255,255,200),width+4,Qt.PenStyle.SolidLine,
                                        Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
                    halo=[QPointF(r.left()+(x+.5)/self.geometry.shape[1]*r.width(),
                                  r.top()+(y+.5)/self.geometry.shape[0]*r.height()) for x,y in roi.points_px]
                    if len(halo)>=2:painter.drawPolyline(halo)
                painter.setPen(QPen(QColor(colour),width,Qt.PenStyle.SolidLine))
            points=[QPointF(r.left()+(x+.5)/self.geometry.shape[1]*r.width(),
                            r.top()+(y+.5)/self.geometry.shape[0]*r.height())
                    for x,y in roi.points_px]
            if roi.kind=='point':
                painter.setBrush(QColor('#ffda55'))
                painter.drawEllipse(points[0],5,5)
            elif len(points)==2 and roi.kind=='rectangle':
                painter.drawRect(QRectF(*points).normalized())
            elif len(points)>=2:
                painter.drawPolyline(points)
                if roi.kind=='line':
                    painter.drawText(QPointF(points[-1].x()+6,points[-1].y()-6),name)
            if roi.kind=='line' and self.tool=='line':
                painter.setBrush(QColor('#ffda55'))
                for point in points:painter.drawEllipse(point,4.5,4.5)
            if roi.kind=='rectangle' and self.tool=='rectangle':
                painter.setBrush(QColor('#ffda55'))
                l,r=sorted((points[0].x(),points[1].x()))
                t,b=sorted((points[0].y(),points[1].y()))
                for x,y in ((l,t),(l,(t+b)/2),(l,b),((l+r)/2,t),((l+r)/2,b),
                            (r,t),(r,(t+b)/2),(r,b)):
                    painter.drawRect(QRectF(x-4,y-4,8,8))
            painter.restore()
        if self._poly_cursor is not None and self.tool=='line' and not self._result:
            found=self._extendable_line()
            if found is not None:
                roi=found[2]
                last=self._to_screen(roi.points_px[-1])
                painter.save()
                painter.setPen(QPen(QColor('#71aee9'),2,Qt.PenStyle.DashLine))
                painter.drawLine(last,self._poly_cursor)
                nxt=self._to_pixel(self._poly_cursor,clamp=True)
                if nxt is not None:
                    absolute,turn=self.segment_angles(list(roi.points_px)+[nxt])
                    text=f'{absolute:.0f}°' + (f'  (turn {turn:+.0f}°)' if turn is not None else '')
                    painter.setPen(QColor('#71aee9'))
                    painter.drawText(QPointF(self._poly_cursor.x()+10,self._poly_cursor.y()+16),
                                     text+'   Shift+click: add segment · Ctrl: 15° steps')
                painter.restore()
        if self.drag_start and self.drag_current and self.tool != 'pan':
            painter.setPen(QPen(QColor('#71aee9'),2,Qt.PenStyle.DashLine))
            if self.tool=='rectangle':
                painter.drawRect(QRectF(self.drag_start,self.drag_current).normalized())
            elif self.tool=='line':
                painter.drawLine(self.drag_start,self.drag_current)
        painter.end()

    def keyReleaseEvent(self,event):
        if event.key()==Qt.Key.Key_Shift and self._poly_cursor is not None:
            self._poly_cursor=None
            self.update()
        super().keyReleaseEvent(event)

    def leaveEvent(self,event):
        if self._poly_cursor is not None:
            self._poly_cursor=None
            self.update()
        super().leaveEvent(event)

    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Shift and self.tool=='line' and self._extendable_line() is not None:
            from PySide6.QtGui import QCursor
            self._poly_cursor=self.mapFromGlobal(QCursor.pos()).toPointF()
            self.update()
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.selected_roi_index >= 0:
            self.deleteSelectedRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def wheelEvent(self,event):
        # A horizontal touchpad gesture (or Shift+wheel) scrolls through
        # channels. It must not be mistaken for a vertical image-zoom gesture.
        delta=event.angleDelta()
        sideways=abs(delta.x())>abs(delta.y())
        shifted=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if sideways or shifted:
            ancestor=self.parentWidget()
            while ancestor is not None and not isinstance(ancestor,QScrollArea):
                ancestor=ancestor.parentWidget()
            if ancestor is not None:
                distance=(event.pixelDelta().x() if sideways else event.pixelDelta().y())
                if not distance:
                    distance=(delta.x() if sideways else delta.y())*2
                bar=ancestor.horizontalScrollBar()
                bar.setValue(bar.value()-round(distance))
                event.accept()
                return
        if self.image is None or delta.y()==0:
            event.ignore()
            return
        factor=1.18 if delta.y()>0 else 1/1.18
        new_zoom=max(.2,min(40.,self.zoom*factor))
        pos=event.position()
        center=QPointF(self.rect().center())
        ratio=new_zoom/self.zoom
        self.pan=QPointF(pos.x()-center.x()-(pos.x()-center.x()-self.pan.x())*ratio,
                         pos.y()-center.y()-(pos.y()-center.y()-self.pan.y())*ratio)
        self.zoom=new_zoom
        self.update()

    def mousePressEvent(self,event):
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if event.button()==Qt.MouseButton.LeftButton:
            self.activated.emit()
        if self.image is None:return
        if event.button() in (Qt.MouseButton.LeftButton,Qt.MouseButton.MiddleButton):
            mods=event.modifiers()
            if (event.button()==Qt.MouseButton.LeftButton and self.tool=='line'
                    and mods & Qt.KeyboardModifier.ShiftModifier):
                found=self._extendable_line()
                if found is not None:
                    target=self._poly_target(event.position(),found[2],
                                             bool(mods & Qt.KeyboardModifier.ControlModifier))
                    point=self._to_pixel(target,clamp=True)
                    if point is not None:
                        self.extend_line(point,found[0],found[1])
                    self._poly_click=True
                    self.drag_start=None
                    return
            if event.button()==Qt.MouseButton.LeftButton and self.tool!='pan':
                self._edit=self._near_handle(event.position())
                if self._edit is not None:
                    self.drag_start=None
                    self.setCursor(Qt.CursorShape.SizeHorCursor)
                    return
                self._press_inside_existing=False
                if self.roi is not None and self.roi.kind=='rectangle' and self.tool=='rectangle':
                    pix=self._to_pixel(event.position())
                    if pix:
                        (x0,y0),(x1,y1)=self.roi.points_px
                        self._press_inside_existing=(min(x0,x1)<pix[0]<max(x0,x1) and
                                                      min(y0,y1)<pix[1]<max(y0,y1))
                        if self._press_inside_existing:return
            self.drag_start=event.position()
            self.drag_current=event.position()
            self._origin_pan=QPointF(self.pan)

    def mouseMoveEvent(self,event):
        mods=event.modifiers()
        if self.tool=='line' and self.drag_start is None and self._edit is None \
                and mods & Qt.KeyboardModifier.ShiftModifier:
            found=self._extendable_line()
            self._poly_cursor=(self._poly_target(event.position(),found[2],
                                                 bool(mods & Qt.KeyboardModifier.ControlModifier))
                               if found is not None else None)
            self.update()
        elif self._poly_cursor is not None:
            self._poly_cursor=None
            self.update()
        if self._edit is not None:
            self._edit_to(event.position())
            return
        if self.drag_start is None and self.tool!='pan':
            self.setCursor(Qt.CursorShape.SizeHorCursor if self._near_handle(event.position()) else Qt.CursorShape.CrossCursor)
        pix=self._to_pixel(event.position())
        if pix is not None and self.data is not None:
            self.cursorPixelChanged.emit(pix)
        if pix and self.data is not None:
            col,row=pix
            j,i=int(round(col)),int(round(row))
            if 0<=i<self.data.shape[0] and 0<=j<self.data.shape[1]:
                try:
                    x,y=self.geometry.pixel_to_local(i,j)
                    u='m' if self.geometry.calibrated else 'px'
                    xv,yv=(x*1e9,y*1e9) if self.geometry.calibrated else (x,y)
                    u='nm' if self.geometry.calibrated else u
                    self.cursorChanged.emit(f'col {j} · row {i}  |  X {float(xv):.4g} {u} · Y {float(yv):.4g} {u}  |  {self.data[i,j]:.5g} {self.unit}')
                except Exception:
                    pass
        if self.drag_start is not None:
            self.drag_current=event.position()
            if self.tool in ('line','rectangle') and self.data is not None:
                p0=self._to_pixel(self.drag_start)
                p1=self._to_pixel(event.position(),clamp=True)
                if p0 and p1 and abs(p0[0]-p1[0])+abs(p0[1]-p1[1])>2:
                    self.roiPreview.emit(ROI('line' if self.tool=='line' else 'rectangle',(p0,p1)))
            if self.tool=='pan' or event.buttons() & Qt.MouseButton.MiddleButton:
                delta=event.position()-self.drag_start
                self.pan=self._origin_pan+delta
            self.update()

    def mouseReleaseEvent(self,event):
        if self._poly_click:
            self._poly_click=False
            return
        if self._edit is not None:
            self._edit_to(event.position())
            origin,index=self._edit[0],self._edit[1]
            self._edit=None
            self.unsetCursor()
            self.roiEdited.emit()
            combined=len(self.extra_rois) if origin=='main' else index
            if 0<=combined<len(self.all_rois()):
                self.selected_roi_index=combined
                self.roiSelected.emit(combined)
            return
        if self.drag_start is not None and event.button()==Qt.MouseButton.LeftButton:
            moved=math.hypot(event.position().x()-self.drag_start.x(),event.position().y()-self.drag_start.y())
            if moved<4 and self.tool!='point' and self._select_at(event.position()) is not None:
                # a click on an existing line / region selects it (Delete removes only that one)
                self.drag_start=self.drag_current=None
                if self.tool=='pan':self.pan=QPointF(self._origin_pan)
                self.update()
                return
        if self.drag_start is not None and self.tool=='point' and self.data is not None:
            point=self._to_pixel(event.position(),clamp=True)
            if point is not None:
                self.roi=ROI('point',(point,))
                self.roiChanged.emit(self.roi)
        elif self.drag_start is not None and self.tool != 'pan' and self.data is not None:
            p1=self._to_pixel(self.drag_start)
            p2=self._to_pixel(event.position(),clamp=True)
            if p1 and p2 and abs(p1[0]-p2[0])+abs(p1[1]-p2[1])>2:
                self.roi=ROI('rectangle' if self.tool=='rectangle' else 'line',(p1,p2))
                if self.roi.kind=='line':
                    self._last_line_pts=tuple(map(tuple,self.roi.points_px))
                self.roiChanged.emit(self.roi)
        self.drag_start=self.drag_current=None
        self.update()


def _segment_distance(p, a, b):
    """Screen distance from point ``p`` (QPointF) to the segment a–b ((x, y) tuples)."""
    px, py = p.x(), p.y()
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 <= 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))
