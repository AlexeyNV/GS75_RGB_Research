"""Original-image scene coordinates, zoom/pan independent from calibration."""
import cv2
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QImage, QPixmap, QPen, QColor, QPolygonF
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsEllipseItem, QGraphicsItem


class LEDItem(QGraphicsEllipseItem):
    def __init__(self,viewer,led,radius):
        super().__init__(-radius,-radius,2*radius,2*radius)
        self.viewer=viewer; self.led_id=led['led_id']; self.start=None
        self.setFlags(QGraphicsItem.ItemIsSelectable|QGraphicsItem.ItemIsMovable|QGraphicsItem.ItemIgnoresTransformations)
        self.setPos(led['x_ref_px'],led['y_ref_px']); self.setZValue(5)
        self.setPen(QPen(QColor('#00d4ff'),2)); self.setBrush(QColor(0,212,255,40))
        self.setToolTip(f"{led['led_id']} | {led['key_name'] or 'Unknown key'} | {led['x_ref_px']:.3f}, {led['y_ref_px']:.3f}\n{led.get('note','')}")

    def mousePressEvent(self,event):
        self.start=self.pos(); self.viewer.ledSelected.emit(self.led_id); super().mousePressEvent(event)

    def mouseReleaseEvent(self,event):
        super().mouseReleaseEvent(event)
        if self.start is not None and self.pos()!=self.start:
            self.viewer.ledMoved.emit(self.led_id,self.pos().x(),self.pos().y())

    def mouseDoubleClickEvent(self,event):
        self.viewer.ledEditRequested.emit(self.led_id); event.accept()


class ImageViewer(QGraphicsView):
    pointClicked=Signal(float,float)
    cursorMoved=Signal(float,float)
    zoomChanged=Signal(float)
    ledSelected=Signal(str)
    ledMoved=Signal(str,float,float)
    ledEditRequested=Signal(str)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self)); self.image_item=None; self.overlays=[]; self.led_items={}; self.labels={}
        self.add_mode=False; self.pan_point=None; self.label_mode='Selected'; self.markers_visible=True
        self.auto_fit=True
        self.setMouseTracking(True); self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn); self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QColor('#20242a'))

    def set_image(self,image):
        rgb=cv2.cvtColor(image,cv2.COLOR_BGR2RGB)
        h,w=rgb.shape[:2]
        pixmap=QPixmap.fromImage(QImage(rgb.data,w,h,rgb.strides[0],QImage.Format_RGB888).copy())
        self.scene().clear(); self.overlays=[]; self.led_items={}; self.labels={}
        self.image_item=self.scene().addPixmap(pixmap); self.image_item.setZValue(0)
        self.scene().setSceneRect(QRectF(0,0,w,h)); self.fit_image()

    def fit_image(self):
        self.auto_fit=True
        if self.image_item:
            self.fitInView(self.image_item,Qt.KeepAspectRatio); self.zoomChanged.emit(self.transform().m11())

    def set_zoom(self,value):
        self.auto_fit=False
        self.resetTransform(); self.scale(value,value); self.zoomChanged.emit(value)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.auto_fit: self.fit_image()

    def wheelEvent(self,event):
        if event.angleDelta().y()==0:
            super().wheelEvent(event); return
        factor=1.2 if event.angleDelta().y()>0 else 1/1.2
        value=self.transform().m11()*factor
        if .01<=value<=64:
            self.auto_fit=False
            self.scale(factor,factor); self.zoomChanged.emit(value)
        event.accept()

    def mousePressEvent(self,event):
        if event.button()==Qt.MiddleButton:
            self.pan_point=event.position(); event.accept(); return
        if self.add_mode and event.button()==Qt.LeftButton and self.image_item:
            point=self.mapToScene(event.position().toPoint())
            if self.sceneRect().contains(point): self.pointClicked.emit(point.x(),point.y())
            event.accept(); return
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        point=self.mapToScene(event.position().toPoint()); self.cursorMoved.emit(point.x(),point.y())
        if self.pan_point is not None:
            delta=event.position()-self.pan_point; self.pan_point=event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value()-round(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value()-round(delta.y()))
            event.accept(); return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MiddleButton: self.pan_point=None; event.accept(); return
        super().mouseReleaseEvent(event)

    def render_map(self,data,radius=7,selected=None):
        for item in self.overlays: self.scene().removeItem(item)
        self.overlays=[]; self.led_items={}; self.labels={}
        for key,corners in data['markers'].items():
            pen=QPen(QColor('#ffca28'),2); pen.setCosmetic(True)
            polygon=self.scene().addPolygon(QPolygonF([QPointF(*p) for p in corners]),pen)
            label=self.scene().addSimpleText(f'ArUco {key}')
            label.setPos(*corners[0]); label.setBrush(QColor('#ffca28'))
            label.setFlag(QGraphicsItem.ItemIgnoresTransformations)
            for item in [polygon,label]: item.setZValue(2); item.setVisible(self.markers_visible)
            self.overlays.extend([polygon,label])
        for led in data['leds']:
            item=LEDItem(self,led,radius); self.scene().addItem(item); self.overlays.append(item)
            label=self.scene().addSimpleText(f"{led['led_id']}  {led['key_name'] or ''}")
            label.setParentItem(item); label.setPos(radius+4,-radius-10); label.setBrush(QColor('#00ffff'))
            label.setAcceptedMouseButtons(Qt.NoButton)
            self.led_items[led['led_id']]=item; self.labels[led['led_id']]=label
        self.select_led(selected)

    def select_led(self,led_id,center=False):
        for key,item in self.led_items.items():
            item.setSelected(key==led_id)
            self.labels[key].setVisible(self.label_mode=='All' or (self.label_mode=='Selected' and key==led_id))
            item.setPen(QPen(QColor('#ff4070' if key==led_id else '#00d4ff'),2))
        if center and led_id in self.led_items: self.centerOn(self.led_items[led_id])
