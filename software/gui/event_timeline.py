"""PTS timeline: electrical, confirmed, candidate, UNKNOWN and OFF lanes."""
from bisect import bisect_left,bisect_right
from statistics import median
from PySide6.QtCore import Qt,Signal,QRectF
from PySide6.QtGui import QPainter,QColor,QPen,QBrush
from PySide6.QtWidgets import QWidget


class EventTimeline(QWidget):
    seek=Signal(float)
    operation_selected=Signal(str)
    view_changed=Signal(float,float)
    LEFT=150
    def __init__(self,parent=None):
        super().__init__(parent);self.report={};self.cursor=0.;self.operations=[];self.alignment={}
        self.view_start=0.;self.view_end=1.;self.timestamps=[];self.hits=[];self.selected_event_ids=set()
        self.setMinimumHeight(185)
        self.setToolTip('Колесо — масштаб по PTS; Shift+колесо — перемещение. UNKNOWN не означает OFF. Электрические окна — USB-оценка, не аппаратная синхронизация.')

    def set_report(self,report):self.report=report;self.reset_view()
    def set_timestamps(self,values):self.timestamps=sorted(values)
    def set_electrical(self,operations,alignment):self.operations=operations;self.alignment=alignment or {};self.update()
    def extent(self):
        maximum=max([e['end_pts'] for e in self.report.get('events',[])]+[u['end_s'] for u in self.report.get('uncertainty_intervals',[])]+[1.])
        video=self.report.get('video') or {}
        return max(maximum,video.get('container_duration_s') or 0.,video.get('duration_s') or 0.)
    def set_view(self,start,end):
        differences=[b-a for a,b in zip(self.timestamps,self.timestamps[1:]) if b>a]
        minimum=median(differences) if differences else 1/((self.report.get('video') or {}).get('fps') or 30.)
        span=min(self.extent(),max(minimum,end-start));start=max(0.,min(start,self.extent()-span))
        self.view_start=start;self.view_end=start+span;self.update();self.view_changed.emit(start,start+span)
    def reset_view(self):self.set_view(0.,self.extent())
    def zoom(self,factor,center=None):
        center=(self.view_start+self.view_end)/2 if center is None else center
        fraction=(center-self.view_start)/max(1e-9,self.view_end-self.view_start)
        span=(self.view_end-self.view_start)/factor;self.set_view(center-fraction*span,center+(1-fraction)*span)
    def pan(self,fraction):
        span=self.view_end-self.view_start;start=fraction*max(0.,self.extent()-span);self.set_view(start,start+span)
    def focus_interval(self,start,end):self.set_view(start-.12,end+.12)
    def position_pts(self,x):return self.view_start+(x-self.LEFT)/max(1,self.width()-self.LEFT-15)*(self.view_end-self.view_start)
    def lanes(self):
        entities=sorted({e['entity'] for e in self.report.get('events',[])}|{u['entity'] for u in self.report.get('uncertainty_intervals',[])}|{o['entity'] for o in self.report.get('off_intervals',[])})
        rows=[('STM32','STM32 USB','')] if self.operations else []
        for entity in entities:
            rows += [('CONFIRMED',entity+' ON',entity),('CANDIDATE',entity+' candidate',entity),('UNKNOWN',entity+' UNKNOWN',entity),('OFF',entity+' OFF',entity)]
        return rows
    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor('#fafafa'));self.hits=[]
        lanes=self.lanes();height=max(13,min(28,(self.height()-30)/max(1,len(lanes))))
        scale=max(1,self.width()-self.LEFT-15)/max(1e-9,self.view_end-self.view_start)
        x=lambda t:self.LEFT+(t-self.view_start)*scale
        colors=dict(RED='#dd4545',GREEN='#32a85a',BLUE='#4386df',MIXED='#a86cbb')
        for row,(kind,label,entity) in enumerate(lanes):
            y=5+row*height;painter.setPen(QColor('#222'));painter.drawText(3,int(y+13),label)
            painter.fillRect(QRectF(self.LEFT,y,self.width()-self.LEFT-15,height-2),QColor('#edf0f2'))
            def bar(start,end,color,pattern=None,key=None,selected=False):
                if end<self.view_start or start>self.view_end:return
                left=max(self.LEFT,x(start));right=min(self.width()-15,x(end));rect=QRectF(left,y,max(2,right-left),height-3)
                painter.fillRect(rect,QBrush(QColor(color),pattern) if pattern else QColor(color))
                if selected:painter.setPen(QPen(QColor('#000'),2));painter.drawRect(rect)
                if key:self.hits.append((rect,key))
            if kind=='STM32':
                offset=self.alignment.get('offset_s')
                if offset is None:
                    painter.drawText(self.LEFT+10,int(y+13),'UNALIGNED / AMBIGUOUS: электрическим операциям PTS не назначены');continue
                for operation in self.operations:
                    if operation.get('host_ack_s') is None:continue
                    start=operation['host_ack_s']-offset;end=start+(operation.get('measured_duration_ms') or operation['requested_duration_ms'])/1000
                    margin=self.alignment.get('uncertainty_s') or 0.
                    bar(start-margin,end+margin,'#8ca6bc',Qt.BDiagPattern);bar(start,end,'#3e6c91',key=operation['operation_key'])
                    if x(end)-x(start)>22 and self.view_start<=start<=self.view_end:
                        painter.setPen(QColor('#fff'));painter.drawText(int(x(start)+2),int(y+13),str(operation.get('operation_id') or '?'))
            elif kind in ('CONFIRMED','CANDIDATE'):
                for e in self.report.get('events',[]):
                    if e['entity']==entity and e['status']==kind:
                        bar(e['start_pts'],e['end_pts'],colors.get(e['color'],'#aaa'),Qt.Dense4Pattern if kind=='CANDIDATE' else None,selected=e['event_id'] in self.selected_event_ids)
            elif kind=='UNKNOWN':
                for u in self.report.get('uncertainty_intervals',[]):
                    if u['entity']==entity:bar(u['start_s'],u['end_s'],'#9a8f7b',Qt.BDiagPattern)
            else:
                for off in self.report.get('off_intervals',[]):
                    if off['entity']==entity:bar(off['start_s'],off['end_s'],'#6f7e88')
        if self.view_end-self.view_start<=1.5:
            painter.setPen(QPen(QColor('#c2cbd1'),1,Qt.DotLine))
            for index in range(bisect_left(self.timestamps,self.view_start),bisect_right(self.timestamps,self.view_end)):
                px=int(x(self.timestamps[index]));painter.drawLine(px,0,px,self.height()-22)
        painter.setPen(QPen(QColor('#161616'),1))
        if self.view_start<=self.cursor<=self.view_end:painter.drawLine(int(x(self.cursor)),0,int(x(self.cursor)),self.height()-20)
        for i in range(7):
            t=self.view_start+i*(self.view_end-self.view_start)/6
            painter.drawText(min(self.width()-65,int(x(t))),self.height()-4,f'{t:.3f}' if self.view_end-self.view_start<2 else f'{t:.1f}')
        painter.end()
    def mousePressEvent(self,event):
        for rect,key in self.hits:
            if rect.contains(event.position()):self.operation_selected.emit(key);return
        self.seek.emit(max(0.,min(self.extent(),self.position_pts(event.position().x()))))
    def wheelEvent(self,event):
        steps=event.angleDelta().y()/120
        if event.modifiers()&Qt.ShiftModifier:
            shift=-steps*(self.view_end-self.view_start)*.15;self.set_view(self.view_start+shift,self.view_end+shift)
        else:self.zoom(1.5**steps,self.position_pts(event.position().x()))
        event.accept()
