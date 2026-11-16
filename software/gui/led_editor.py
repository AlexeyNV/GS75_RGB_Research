from PySide6.QtWidgets import QWidget,QFormLayout,QLineEdit,QDoubleSpinBox,QPlainTextEdit,QPushButton,QDialog,QDialogButtonBox,QVBoxLayout,QLabel


class LEDEditor(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent); form=QFormLayout(self)
        self.id=QLineEdit(); self.key=QLineEdit(); self.note=QPlainTextEdit(); self.note.setMaximumHeight(75)
        self.x=QDoubleSpinBox(); self.y=QDoubleSpinBox()
        for spin in [self.x,self.y]: spin.setRange(0,100000); spin.setDecimals(6)
        for name,field in [('LED ID',self.id),('Key name (optional)',self.key),('X reference px',self.x),('Y reference px',self.y),('Note',self.note)]: form.addRow(name,field)
        self.apply=QPushButton('Apply changes'); form.addRow(self.apply)

    def populate(self,led):
        self.id.setText(led['led_id']); self.key.setText(led['key_name'] or '')
        self.x.setValue(led['x_ref_px']); self.y.setValue(led['y_ref_px']); self.note.setPlainText(led.get('note',''))
        self.original_xy=(led['x_ref_px'],led['y_ref_px'])
        self.displayed_xy=(self.x.value(),self.y.value())

    def values(self):
        x,y=self.x.value(),self.y.value()
        if hasattr(self,'displayed_xy'):
            if x==self.displayed_xy[0]: x=self.original_xy[0]
            if y==self.displayed_xy[1]: y=self.original_xy[1]
        return dict(led_id=self.id.text().strip(),key_name=self.key.text().strip() or None,
                    x_ref_px=x,y_ref_px=y,note=self.note.toPlainText())


class LEDDialog(QDialog):
    def __init__(self,x,y,led_id='',key_name='',parent=None):
        super().__init__(parent); self.setWindowTitle('Add LED - identify PCB marking explicitly')
        layout=QVBoxLayout(self); self.editor=LEDEditor(); self.editor.apply.hide()
        self.editor.populate(dict(led_id=led_id,key_name=key_name,x_ref_px=x,y_ref_px=y))
        layout.addWidget(QLabel('LED ID is independent of key name. No key mapping is inferred.'))
        layout.addWidget(self.editor)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.editor.id.setFocus()
