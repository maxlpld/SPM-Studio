"""Lightweight Qt scientific previews with direct, non-destructive mask editing."""
from __future__ import annotations
import numpy as np
from PySide6.QtCore import Qt,QRectF,QPointF,Signal
from PySide6.QtGui import QColor,QPainter,QPen,QPainterPath
from PySide6.QtWidgets import QWidget


class LivePlot(QWidget):
    """Edit exactly one mask boundary; a drag on empty space sets a new interval.

    Moving a mask as a whole is deliberately unsupported: accidentally dragging a
    filled band must never move both boundaries. No Python analysis runs while
    dragging; only a small Qt plot is repainted, and the selected mask is committed
    on release. `rangePreview` streams a temporary interval for image overlays.
    """
    rangePreview=Signal(float,float)
    rangeEdited=Signal(float,float)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setMinimumHeight(210)
        self.setMouseTracking(True)
        self.mode='hist';self.series=[];self.ranges=[];self.selected=-1
        self.low=0.;self.high=1.;self._chart=QRectF()
        self._drag=None;self._temporary=None
        self.title='Live analysis preview'

    def histogram(self,values,bins=100,ranges=None,selected=-1):
        a=np.asarray(values)
        a=a[np.isfinite(a)]
        if a.size:
            lo,hi=float(np.min(a)),float(np.max(a))
            if hi<=lo:hi=lo+max(abs(lo)*1e-9,1e-12)
            self.low,self.high=lo,hi
            y,edges=np.histogram(a,bins=max(16,min(int(bins),512)),range=(lo,hi))
            self.series=[('Distribution',(edges[:-1]+edges[1:])/2,y)]
        else:self.series=[]
        self.ranges=list(ranges or [])
        self.selected=selected
        self.mode='hist'
        self.title='Drag an edge handle • drag empty space to set interval'
        self.update()

    def profiles(self,series):
        self.mode='profiles';self.series=series;self.ranges=[]
        self.title='Line profiles (drag the endpoints on the scan)'
        self.update()

    def _value_from_x(self,x):
        if self._chart.width()<=0:return self.low
        fraction=min(1.,max(0.,(x-self._chart.left())/self._chart.width()))
        return self.low+fraction*(self.high-self.low)

    def _x_from_value(self,value):
        span=self.high-self.low
        return self._chart.left()+self._chart.width()*(value-self.low)/span if span>0 else self._chart.left()

    def _selected_range(self):
        if 0<=self.selected<len(self.ranges):
            return self.ranges[self.selected]
        return None

    def _handle(self,pos):
        mask=self._selected_range()
        if not mask or not self._chart.contains(pos):return None
        d0=abs(pos.x()-self._x_from_value(mask['low']))
        d1=abs(pos.x()-self._x_from_value(mask['high']))
        nearest='low' if d0<=d1 else 'high'
        return nearest if min(d0,d1)<=12 else None

    def mousePressEvent(self,event):
        if self.mode!='hist' or event.button()!=Qt.MouseButton.LeftButton:return
        if not self._chart.contains(event.position()):return
        mask=self._selected_range()
        if mask is None:return # user must first select/create a named mask
        edge=self._handle(event.position())
        if edge is None:
            left=self._x_from_value(mask['low']);right=self._x_from_value(mask['high'])
            if min(left,right)<event.position().x()<max(left,right):
                return # Never move a whole interval by accident
            edge='new'
        self._drag=(edge,self._value_from_x(event.position().x()),float(mask['low']),float(mask['high']))
        self.grabMouse()
        self.setCursor(Qt.CursorShape.SizeHorCursor if edge!='new' else Qt.CursorShape.CrossCursor)
        self.update()

    def mouseMoveEvent(self,event):
        if self._drag is None:
            cursor=Qt.CursorShape.SizeHorCursor if self._handle(event.position()) else Qt.CursorShape.ArrowCursor
            self.setCursor(cursor)
            return
        kind,start,lo,hi=self._drag
        value=self._value_from_x(event.position().x())
        if kind=='low':lo=min(value,hi)
        elif kind=='high':hi=max(value,lo)
        else:lo,hi=sorted((start,value))
        self._temporary=(lo,hi)
        self.rangePreview.emit(lo,hi)
        self.update()

    def mouseReleaseEvent(self,event):
        if self._drag is None:return
        self.mouseMoveEvent(event)
        result=self._temporary
        self._drag=None;self._temporary=None
        self.releaseMouse();self.unsetCursor()
        if result is not None and result[1]>result[0]:
            self.rangeEdited.emit(*result)
        self.update()

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        from spm_studio.shared.appearance import colors
        ui=colors(self)
        p.fillRect(self.rect(),QColor(ui['surface']))
        area=QRectF(60,28,max(12,self.width()-76),max(18,self.height()-77))
        self._chart=area
        p.setPen(QColor(ui['foreground']))
        font=p.font();font.setPointSize(8);p.setFont(font)
        p.drawText(QRectF(10,3,self.width()-20,23),Qt.AlignmentFlag.AlignLeft,self.title)
        p.setPen(QPen(QColor(ui['border']),1))
        p.drawLine(area.bottomLeft(),area.topLeft());p.drawLine(area.bottomLeft(),area.bottomRight())
        finite=[]
        for item in self.series:
            x,y=item[1],item[2]
            x=np.asarray(x);y=np.asarray(y);mask=np.isfinite(x)&np.isfinite(y)
            if mask.any():finite.append((x[mask],y[mask]))
        if not finite:
            p.drawText(area,Qt.AlignmentFlag.AlignCenter,'Select an image or draw a line')
            p.end();return
        lo=min(float(np.min(x)) for x,_ in finite)
        hi=max(float(np.max(x)) for x,_ in finite)
        yl=min(float(np.min(y)) for _,y in finite)
        yh=max(float(np.max(y)) for _,y in finite)
        if hi<=lo:hi=lo+1
        if yh<=yl:yh=yl+1
        yl=min(0,yl);yr=(yh-yl)*1.06
        if yr<=0:yr=1
        for n,r in enumerate(self.ranges):
            a,b=float(r['low']),float(r['high'])
            if n==self.selected and self._temporary is not None:a,b=self._temporary
            x1=self._x_from_value(a) if self.mode=='hist' else area.left()+area.width()*(a-lo)/(hi-lo)
            x2=self._x_from_value(b) if self.mode=='hist' else area.left()+area.width()*(b-lo)/(hi-lo)
            color=QColor(r.get('color','#e6b15e'))
            color.setAlpha(92 if n==self.selected else 36)
            p.fillRect(QRectF(QPointF(x1,area.top()),QPointF(x2,area.bottom())).normalized().intersected(area),color)
            if n==self.selected:
                border=QColor(r.get('color','#e6b15e'))
                p.setPen(QPen(border,2))
                for x in (x1,x2):
                    x=max(area.left(),min(area.right(),x))
                    p.drawLine(QPointF(x,area.top()),QPointF(x,area.bottom()))
                    p.fillRect(QRectF(x-5,area.center().y()-11,10,22),border)
                p.setPen(QColor(ui['foreground']))
                p.drawText(QRectF(area.left(),area.bottom()+21,area.width(),17),
                           Qt.AlignmentFlag.AlignCenter,f'{a:.6g}     to     {b:.6g}  (SI)')
        for i,item in enumerate(self.series):
            x,y=item[1],item[2]
            x=np.asarray(x);y=np.asarray(y);valid=np.isfinite(x)&np.isfinite(y);x=x[valid];y=y[valid]
            if len(x)<2:continue
            path=QPainterPath()
            for j,(xx,yy) in enumerate(zip(x,y)):
                px=area.left()+area.width()*(float(xx)-lo)/(hi-lo)
                py=area.bottom()-area.height()*(float(yy)-yl)/yr
                if j==0:path.moveTo(px,py)
                else:path.lineTo(px,py)
            colour=item[3] if len(item)>3 else ['#6db5ee','#efbb64','#86dba9','#dc96ef'][i%4]
            p.setPen(QPen(QColor(colour),1.5))
            p.drawPath(path)
        p.setPen(QColor(ui['foreground']))
        p.drawText(QRectF(area.left(),area.bottom()+3,area.width()*.5,15),f'{lo:.4g}')
        p.drawText(QRectF(area.center().x(),area.bottom()+3,area.width()*.5,15),Qt.AlignmentFlag.AlignRight,f'{hi:.4g}')
        p.drawText(QRectF(1,area.top(),55,15),Qt.AlignmentFlag.AlignRight,f'{yh:.3g}')
        p.end()
