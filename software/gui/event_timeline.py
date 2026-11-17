"""Clickable PTS timeline. Hatched intervals are unknown, never default OFF."""
from PySide6.QtCore import Qt,Signal,QRectF
from PySide6.QtGui import QPainter,QColor,QPen,QBrush
from PySide6.QtWidgets import QWidget


class EventTimeline(QWidget):
    seek=Signal(float)
    def __init__(self,parent=None):
        super().__init__(parent);self.report={};self.cursor=0.;self.setMinimumHeight(140)
        self.setToolTip('Цвет — гипотеза ON; серый OFF — только надёжные наблюдения; штриховка — неопределённость. Нажмите для перехода.')

    def set_report(self,report):self.report=report;self.update()
    def extent(self):
        maximum=max([e['end_pts'] for e in self.report.get('events',[])]+[u['end_s'] for u in self.report.get('uncertainty_intervals',[])]+[1.])
        return max(maximum,(self.report.get('video') or {}).get('container_duration_s') or 0.)
    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor('#fafafa'))
        names=sorted({e['entity'] for e in self.report.get('events',[])}|{u['entity'] for u in self.report.get('uncertainty_intervals',[])}|{o['entity'] for o in self.report.get('off_intervals',[])})
        scale=max(1,self.width()-125)/self.extent();height=max(18,min(28,(self.height()-25)/max(1,len(names))))
        color=dict(RED='#dd4545',GREEN='#32a85a',BLUE='#4386df',MIXED='#a86cbb')
        x=lambda t:110+t*scale
        for row,name in enumerate(names):
            y=5+row*height;painter.setPen(QColor('#222'));painter.drawText(3,int(y+15),name)
            for off in self.report.get('off_intervals',[]):
                if off['entity']==name:painter.fillRect(QRectF(x(off['start_s']),y,max(2,(off['end_s']-off['start_s'])*scale),height-3),QColor('#6f7e88'))
            for e in self.report.get('events',[]):
                if e['entity']!=name:continue
                c=QColor(color.get(e['color'],'#aaa'));c.setAlpha(220 if e['status']=='CONFIRMED' else 65)
                painter.fillRect(QRectF(x(e['start_pts']),y,max(2,e['duration_s']*scale),height-3),c)
            for u in self.report.get('uncertainty_intervals',[]):
                if u['entity']!=name:continue
                painter.fillRect(QRectF(x(u['start_s']),y,max(2,(u['end_s']-u['start_s'])*scale),height-3),QBrush(QColor('#9a8f7b'),Qt.BDiagPattern))
        painter.setPen(QPen(QColor('#161616'),1));painter.drawLine(int(x(self.cursor)),0,int(x(self.cursor)),self.height()-20)
        for i in range(7):
            t=i*self.extent()/6;painter.drawText(min(self.width()-45,int(x(t))),self.height()-4,f'{t:.1f}')
        painter.end()
    def mousePressEvent(self,event):
        value=max(0,min(self.extent(),(event.position().x()-110)/max(1,self.width()-125)*self.extent()))
        self.seek.emit(value)
