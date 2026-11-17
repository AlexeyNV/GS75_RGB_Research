"""Qt calibrator. All model edits are transactional and independent of view scale."""
import json
from pathlib import Path
import uuid
from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QAction,QKeySequence
from PySide6.QtWidgets import (QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QSplitter,QToolBar,QLabel,
    QFileDialog,QMessageBox,QTableWidget,QTableWidgetItem,QLineEdit,QComboBox,QSpinBox,QCheckBox,
    QPushButton,QInputDialog,QApplication)
from software.vision import calibration
from software.vision.project_storage import ROOT,atomic_json,read_image
from .image_viewer import ImageViewer
from .led_editor import LEDEditor,LEDDialog
from . import ensure_fonts


class NumericItem(QTableWidgetItem):
    def __lt__(self,other):
        if self.column()==0:
            return int(self.text()[3:])<int(other.text()[3:])
        return super().__lt__(other)


class Calibrator(QMainWindow):
    def __init__(self,root=ROOT):
        ensure_fonts(); super().__init__(); self.root=Path(root); self.document=None; self.reference_image=None
        self.project_path=None; self.selected=None; self.last_key=''; self.camera=None
        self.draft_path=self.root/'build/vision/autosave'/f'{uuid.uuid4().hex}.autosave.json'
        self.setWindowTitle('GS75 RGB Vision v0.1 - Board Calibrator'); self.resize(1450,900)
        self.viewer=ImageViewer(); side=QWidget(); layout=QVBoxLayout(side)
        self.summary=QLabel('Open reference photograph to begin'); self.summary.setWordWrap(True); layout.addWidget(self.summary)
        self.search=QLineEdit(); self.search.setPlaceholderText('Find LED ID or key name'); layout.addWidget(self.search)
        self.table=QTableWidget(0,4); self.table.setHorizontalHeaderLabels(['LED ID','Key name','X','Y'])
        self.table.setSelectionBehavior(QTableWidget.SelectRows); self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSortingEnabled(True); layout.addWidget(self.table,1)
        self.editor=LEDEditor(); self.editor.setEnabled(False); layout.addWidget(self.editor)
        self.comment=QLineEdit(); self.comment.setPlaceholderText('Project comment (Enter to apply)'); layout.addWidget(self.comment)
        controls=QHBoxLayout(); self.autonumber=QCheckBox('Explicit auto-ID'); self.autonumber.setToolTip('Off by default; uses next numeric ID only when explicitly enabled')
        self.labels=QComboBox(); self.labels.addItems(['Selected','All','None'])
        self.radius=QSpinBox(); self.radius.setRange(3,30); self.radius.setValue(7)
        controls.addWidget(self.autonumber); controls.addWidget(QLabel('Labels')); controls.addWidget(self.labels)
        controls.addWidget(QLabel('Marker px')); controls.addWidget(self.radius); layout.addLayout(controls)
        split=QSplitter(); split.addWidget(self.viewer); split.addWidget(side); split.setSizes([1000,450]); self.setCentralWidget(split)
        self.actions={}; toolbar=QToolBar('Calibration'); self.addToolBar(toolbar)
        def action(name,callback,shortcut=None,checkable=False):
            item=QAction(name,self); item.setCheckable(checkable)
            item.triggered.connect(callback)
            if shortcut: item.setShortcut(QKeySequence(shortcut))
            toolbar.addAction(item); self.actions[name]=item; return item
        action('Open Photo',self.open_photo,'Ctrl+I'); action('Open Map',self.open_map,'Ctrl+O')
        action('Save',self.save_map,'Ctrl+S'); action('Save As',lambda:self.save_map(True),'Ctrl+Shift+S')
        action('Add LED',self.toggle_add,'A',True); action('Delete',self.delete_led,'Ctrl+Delete')
        action('Undo',self.undo,'Ctrl+Z'); action('Redo',self.redo,'Ctrl+Y')
        action('Fit',self.viewer.fit_image,'F'); action('100%',lambda:self.viewer.set_zoom(1))
        action('200%',lambda:self.viewer.set_zoom(2)); action('400%',lambda:self.viewer.set_zoom(4))
        action('ArUco',self.toggle_markers,checkable=True).setChecked(True)
        action('Marker Profile',self.marker_profile); action('Camera Model',self.camera_model)
        action('Analyze Images',self.analyze_images)
        self.coords=QLabel(); self.resolution=QLabel(); self.zoom=QLabel()
        for label in [self.resolution,self.coords,self.zoom]: self.statusBar().addPermanentWidget(label)
        self.viewer.pointClicked.connect(self.add_at); self.viewer.ledSelected.connect(self.select_led)
        self.viewer.ledMoved.connect(self.move_led); self.viewer.ledEditRequested.connect(self.focus_editor)
        self.viewer.cursorMoved.connect(lambda x,y:self.coords.setText(f'Pixel ({x:.2f}, {y:.2f})'))
        self.viewer.zoomChanged.connect(lambda z:self.zoom.setText(f'{z*100:.1f}%'))
        self.table.cellClicked.connect(self.table_selected); self.search.textChanged.connect(self.filter_table)
        self.editor.apply.clicked.connect(self.apply_edit); self.labels.currentTextChanged.connect(self.refresh_labels)
        self.radius.valueChanged.connect(self.refresh); self.comment.returnPressed.connect(self.apply_comment)
        self.timer=QTimer(self); self.timer.setInterval(30000); self.timer.timeout.connect(self.autosave); self.timer.start()
        self.refresh()

    def error(self,exc): QMessageBox.warning(self,'RGB Vision',str(exc))

    def confirm_discard(self):
        if self.document and self.document.dirty:
            answer=QMessageBox.question(self,'Unsaved map','Save changes before continuing?',QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel)
            if answer==QMessageBox.Cancel: return False
            if answer==QMessageBox.Save: return self.save_map()
        return True

    def open_photo(self):
        if not self.confirm_discard(): return
        path,_=QFileDialog.getOpenFileName(self,'Open reference photograph','','Images (*.jpg *.jpeg *.png *.tif *.tiff)')
        if path:
            try: self.set_reference(path)
            except Exception as exc: self.error(exc)

    def set_reference(self,path,camera=None):
        data,image=calibration.create(path,self.root,camera or self.camera)
        self.document=calibration.Document(data); self.reference_image=image; self.project_path=None; self.selected=None
        self.viewer.set_image(image); self.refresh()
        return data

    def open_map(self):
        if not self.confirm_discard(): return
        path,_=QFileDialog.getOpenFileName(self,'Open calibration / recovery draft',str(self.root/'config'),'JSON (*.json)')
        if path:
            try: self.load_map(path)
            except Exception as exc: self.error(exc)

    def load_map(self,path):
        data=calibration.load(path,self.root)
        document=calibration.Document(data); document.mark_saved()
        draft=Path(str(path)+'.autosave.json')
        if draft.exists() and draft.stat().st_mtime>Path(path).stat().st_mtime:
            if QMessageBox.question(self,'Recovery draft','A newer autosave exists. Recover it?')==QMessageBox.Yes:
                document.data=calibration.load(draft,self.root)
        image=read_image(self.root/document.data['reference']['path'],document.data.get('camera_model'))
        self.document=document; self.reference_image=image; self.project_path=Path(path); self.selected=None
        self.viewer.set_image(image); self.refresh()

    def save_map(self,save_as=False):
        if not self.document: return False
        path=self.project_path
        if save_as or path is None:
            value,_=QFileDialog.getSaveFileName(self,'Save calibration',str(path or self.root/'config/gs75_board_calibration.json'),'JSON (*.json)')
            if not value: return False
            path=Path(value)
        try:
            self.document.save(path); self.project_path=path; self.refresh()
            self.statusBar().showMessage(f'Saved {path}',5000); return True
        except Exception as exc: self.error(exc); return False

    def autosave(self):
        if self.document and self.document.dirty:
            path=Path(str(self.project_path)+'.autosave.json') if self.project_path else self.draft_path
            try: atomic_json(path,self.document.data); self.statusBar().showMessage(f'Draft saved: {path}',5000)
            except Exception as exc: self.statusBar().showMessage(f'Autosave failed: {exc}',10000)

    def closeEvent(self,event):
        if self.confirm_discard(): event.accept()
        else: event.ignore()

    def toggle_add(self,checked):
        self.viewer.add_mode=checked; self.statusBar().showMessage('Click LED center; middle mouse pans' if checked else 'Select/drag LED; drag background to pan')

    def add_at(self,x,y,suggest_id=True):
        if not self.document: return
        identifier=''
        if suggest_id and self.autonumber.isChecked():
            identifier=f"LED{max([int(l['led_id'][3:]) for l in self.document.data['leds']]+[0])+1}"
        dialog=LEDDialog(x,y,identifier,self.last_key,self)
        while dialog.exec():
            values=dialog.editor.values()
            try:
                self.document.add(values['led_id'],values['key_name'],values['x_ref_px'],values['y_ref_px'],values['note'])
                self.last_key=values['key_name'] or ''; self.selected=values['led_id']; self.refresh(); break
            except Exception as exc: self.error(exc)

    def select_led(self,identifier,center=False):
        if not self.document: return
        led=next((l for l in self.document.data['leds'] if l['led_id']==identifier),None)
        if not led: return
        self.selected=identifier; self.viewer.select_led(identifier,center)
        self.editor.populate(led); self.editor.setEnabled(True)
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            if self.table.item(row,0).text()==identifier: self.table.selectRow(row); break
        self.table.blockSignals(False)

    def table_selected(self,row,column): self.select_led(self.table.item(row,0).text(),True)
    def focus_editor(self,identifier): self.select_led(identifier); self.editor.id.setFocus()

    def apply_edit(self):
        if self.document and self.selected:
            try:
                values=self.editor.values(); self.document.edit(self.selected,**values); self.selected=values['led_id']; self.refresh()
            except Exception as exc: self.error(exc)

    def move_led(self,identifier,x,y):
        try: self.document.edit(identifier,x_ref_px=x,y_ref_px=y)
        except Exception as exc: self.error(exc)
        self.selected=identifier; self.refresh()

    def delete_led(self):
        if self.document and self.selected:
            self.document.delete(self.selected); self.selected=None; self.refresh()

    def undo(self):
        if self.document: self.document.undo(); self.refresh()
    def redo(self):
        if self.document: self.document.redo(); self.refresh()

    def apply_comment(self):
        if self.document:
            value=self.comment.text(); self.document.change(lambda data:data['metadata'].update(comment=value)); self.refresh()

    def refresh_labels(self,value):
        self.viewer.label_mode=value; self.viewer.select_led(self.selected)

    def toggle_markers(self,checked): self.viewer.markers_visible=checked; self.refresh()

    def filter_table(self):
        value=self.search.text().casefold()
        for row in range(self.table.rowCount()):
            self.table.setRowHidden(row,value not in (self.table.item(row,0).text()+' '+self.table.item(row,1).text()).casefold())

    def refresh(self,*args):
        if not self.document:
            self.actions['Undo'].setEnabled(False); self.actions['Redo'].setEnabled(False); return
        data=self.document.data; reference=data['reference']
        self.resolution.setText(f"{reference['width']} x {reference['height']} original px")
        missing=set(map(str,data['expected_marker_ids']))-set(data['markers'])
        self.summary.setText(f"{len(data['leds'])} LEDs | {len(data['markers'])} ArUco detected\n"+
                             ('Warning: expected markers missing: '+', '.join(sorted(missing)) if missing else 'Expected marker profile complete')+
                             '\nReference pixels; physical mm NOT calibrated')
        self.table.blockSignals(True); self.table.setSortingEnabled(False); self.table.setRowCount(len(data['leds']))
        for row,led in enumerate(data['leds']):
            for col,value in enumerate([led['led_id'],led['key_name'] or '',led['x_ref_px'],led['y_ref_px']]):
                item=NumericItem() if col==0 else QTableWidgetItem()
                item.setData(Qt.DisplayRole,value); self.table.setItem(row,col,item)
        self.table.setSortingEnabled(True); self.table.blockSignals(False); self.filter_table()
        self.viewer.render_map(data,self.radius.value(),self.selected)
        self.editor.setEnabled(False)
        if self.selected: self.select_led(self.selected)
        self.comment.setText(data['metadata'].get('comment',''))
        self.actions['Undo'].setEnabled(bool(self.document.past)); self.actions['Redo'].setEnabled(bool(self.document.future))
        self.setWindowTitle(f"GS75 RGB Vision v0.1 - {self.project_path.name if self.project_path else 'New map'}{' *' if self.document.dirty else ''}")

    def marker_profile(self):
        if not self.document: return
        path,_=QFileDialog.getOpenFileName(self,'Load markers_manifest.json',str(self.root/'build/markers'),'JSON (*.json)')
        if not path: return
        try:
            manifest=json.loads(Path(path).read_text(encoding='utf-8'))
            if manifest['dictionary']!='DICT_4X4_50': raise ValueError('Wrong marker dictionary')
            def update(data):
                data['expected_marker_ids']=[m['id'] for m in manifest['markers']]
                data['sticker_sizes_mm']={str(m['id']):m['sticker_mm'] for m in manifest['markers']}
            self.document.change(update); self.refresh()
        except Exception as exc: self.error(exc)

    def camera_model(self):
        if self.document:
            self.error('Load camera model before opening a new reference. Existing map geometry cannot be silently changed.'); return
        path,_=QFileDialog.getOpenFileName(self,'Load verified camera intrinsics','','JSON (*.json)')
        if path:
            try:
                self.camera=json.loads(Path(path).read_text(encoding='utf-8')); self.statusBar().showMessage('Camera model selected for new reference')
            except Exception as exc: self.error(exc)

    def analyze_images(self):
        if not self.document: return
        try:
            from .image_comparator import analyze_dialog
            analyze_dialog(self)
        except Exception as exc: self.error(exc)
