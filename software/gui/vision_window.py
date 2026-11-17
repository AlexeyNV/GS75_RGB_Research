"""Unified research application with explicit operator-controlled LED49 experiments."""
from copy import deepcopy
import json
import logging
from pathlib import Path
import shutil
from PIL import Image,ImageOps
from PySide6.QtCore import Qt,QTimer,QThreadPool,QSettings,QSize,Signal
from PySide6.QtGui import QAction,QIcon,QImage,QPixmap
from PySide6.QtWidgets import (QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QTabWidget,
    QPushButton,QLabel,QListWidget,QListWidgetItem,QFileDialog,QMessageBox,QComboBox,
    QTableWidget,QTableWidgetItem,QPlainTextEdit,QProgressBar,QSplitter,QFormLayout,
    QSpinBox,QDoubleSpinBox,QLineEdit,QInputDialog,QSlider,QAbstractItemView,QMenu)
from .board_calibrator import Calibrator
from .image_viewer import ImageViewer
from .jobs import Job
from .result_pane import ResultPane
from .performance_pane import PerformancePane
from .experiment_pane import ExperimentPane
from . import ensure_fonts
from software.vision import calibration
from software.vision.project_storage import ROOT,read_image,image_hash,write_image
from software.vision.research_project import (ResearchProject,DEFAULTS,PHOTO_EXTENSIONS,
    VIDEO_EXTENSIONS,batch,checkpoint)
from software.vision.video_source import VideoReader


def button(layout,text,callback):
    value=QPushButton(text);value.clicked.connect(callback);layout.addWidget(value);return value


class MediaList(QListWidget):
    pathsDropped=Signal(list)
    def __init__(self):
        super().__init__();self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection);self.setIconSize(QSize(110,80));self.setSpacing(4)
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls():event.acceptProposedAction()
    def dragMoveEvent(self,event):
        if event.mimeData().hasUrls():event.acceptProposedAction()
    def dropEvent(self,event):
        self.pathsDropped.emit([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]);event.acceptProposedAction()


class EmbeddedCalibrator(Calibrator):
    def __init__(self,owner):
        self.owner=owner;super().__init__(ROOT);self.setWindowFlags(Qt.Widget)
        for action in self.actions.values():action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        for key,text in [('Open Photo','Эталон'),('Open Map','Открыть карту'),('Save','Сохранить карту'),('Add LED','Добавить LED')]:
            self.actions[key].setText(text)
    def open_photo(self):self.owner.choose_reference()
    def open_map(self):self.owner.choose_calibration()
    def analyze_images(self):self.owner.tabs.setCurrentWidget(self.owner.photos_page)
    def save_map(self,save_as=False):
        ok=super().save_map(save_as)
        if ok and self.owner.project:
            self.owner.bind_saved_map();self.owner.save_project()
        return ok
    def error(self,exc):self.owner.error(str(exc))


class VisionWindow(QMainWindow):
    def __init__(self,remember=True):
        ensure_fonts();super().__init__();self.setWindowTitle('GS75 RGB Vision v0.4.1');self.resize(1500,980)
        self.project=None;self.active_job=None;self.job_callback=None;self.pool=QThreadPool(self);self.pool.setMaxThreadCount(1)
        self.remember=remember;self.preferences=QSettings('GS75_RGB_Research','RGBVision')
        self.decoder=VideoReader();self.video_path=None;self.video_image=None;self.frame_info=None
        self.video_meta=None;self.playing=False;self.pending_result=None;self.pending_frame=None
        self.tabs=QTabWidget();self.setCentralWidget(self.tabs)
        self.project_page=QWidget();layout=QVBoxLayout(self.project_page)
        self.project_info=QLabel('Создайте или откройте проект исследования.');self.project_info.setWordWrap(True);layout.addWidget(self.project_info)
        row=QHBoxLayout();button(row,'Создать проект',self.new_dialog);button(row,'Открыть проект',self.open_dialog)
        button(row,'Сохранить проект',self.save_project);button(row,'Найти перемещённые файлы',self.relink_files);layout.addLayout(row)
        self.recent=QComboBox();self.refresh_recent();layout.addWidget(self.recent)
        button(layout,'Открыть недавний',lambda:self.open_project(self.recent.currentData()) if self.recent.currentData() else None)
        button(layout,'Выбрать карту калибровки',self.choose_calibration);layout.addStretch()
        self.suggested_map=QLabel();self.suggested_map.setWordWrap(True);layout.addWidget(self.suggested_map)
        button(layout,'Использовать предложенную карту',self.use_suggested_map)
        self.calibrator=EmbeddedCalibrator(self)
        self.photos_page=QWidget();layout=QVBoxLayout(self.photos_page);row=QHBoxLayout()
        button(row,'Добавить фотографии',self.import_dialog)
        self.role=QComboBox();self.role.addItems(['UNASSIGNED','OFF','ON','REFERENCE']);row.addWidget(self.role)
        button(row,'Назначить роль',self.assign_selected);button(row,'Сравнить выбранные',self.compare_selected)
        button(row,'Анализировать выбранные ON',self.analyze_selected)
        self.analysis_mode=QComboBox();self.analysis_mode.addItems(['KNOWN_LEDS','DISCOVER']);row.addWidget(self.analysis_mode);layout.addLayout(row)
        split=QSplitter();self.media_list=MediaList();split.addWidget(self.media_list)
        self.photo_viewer=ImageViewer();split.addWidget(self.photo_viewer);split.setSizes([400,1000]);layout.addWidget(split,1)
        self.media_list.pathsDropped.connect(self.import_paths);self.media_list.itemClicked.connect(self.preview_media)
        self.media_list.setContextMenuPolicy(Qt.CustomContextMenu);self.media_list.customContextMenuRequested.connect(self.media_menu)
        self.video_page=QWidget();layout=QVBoxLayout(self.video_page);row=QHBoxLayout()
        button(row,'Открыть видео',self.video_dialog);button(row,'▶ / ❚❚',self.play_pause)
        button(row,'Предыдущий кадр',lambda:self.step_video(-1));button(row,'Следующий кадр',lambda:self.step_video(1))
        button(row,'Кадр как OFF',lambda:self.use_frame('OFF'));button(row,'Кадр как ON',lambda:self.use_frame('ON'))
        button(row,'Сохранить кадр',self.save_frame_dialog);layout.addLayout(row)
        self.video_viewer=ImageViewer();layout.addWidget(self.video_viewer,1)
        self.video_slider=QSlider(Qt.Horizontal);self.video_slider.setRange(0,0);layout.addWidget(self.video_slider)
        self.video_label=QLabel('Откройте MP4 / MOV / AVI. Поддержка зависит от декодера.');layout.addWidget(self.video_label)
        self.video_slider.sliderReleased.connect(lambda:self.request_frame(self.video_slider.value()))
        self.play_timer=QTimer(self);self.play_timer.timeout.connect(self.advance_video)
        self.results_page=QWidget();layout=QVBoxLayout(self.results_page);row=QHBoxLayout()
        self.history=QComboBox();row.addWidget(self.history,1);button(row,'Открыть',self.open_history)
        button(row,'Переименовать',self.rename_history);button(row,'Повторить',self.repeat_history)
        button(row,'Экспортировать',self.export_history);button(row,'Сравнить запуски',self.compare_runs);layout.addLayout(row)
        self.batch_table=QTableWidget(0,5);self.batch_table.setHorizontalHeaderLabels(['Файл / опыт','LED','Статус','Цвет','Регистрация / ошибка'])
        self.batch_table.setSelectionBehavior(QAbstractItemView.SelectRows);self.batch_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.batch_table.setMaximumHeight(160);layout.addWidget(self.batch_table)
        self.batch_table.horizontalHeader().setStretchLastSection(True);self.batch_table.setColumnWidth(0,170)
        self.batch_table.cellClicked.connect(self.open_report_row);self.report_rows=[]
        self.result_pane=ResultPane(self);layout.addWidget(self.result_pane,1)
        self.settings_page=QWidget();form=QFormLayout(self.settings_page)
        self.profile=QComboBox();self.profile.addItems(['Auto / Recommended','Advanced']);form.addRow('Профиль',self.profile)
        self.setting_controls={}
        for key,title,limits in [
            ('threshold','Порог яркости',(1,255,30)),('color_threshold','Порог новой цветности',(1,255,25)),
            ('roi_radius','Радиус ROI, px',(5,500,40)),('min_area','Минимальная цветовая площадь',(1,100000,6)),
            ('registration_error','RANSAC / RMSE, px',(.5,10,3)),
            ('dominance_ratio','Предел побочного / основного',(.01,.69,.45)),('mixed_ratio','Порог смешанного цвета',(.1,1,.70))]:
            spin=QSpinBox() if key in ('threshold','color_threshold','roi_radius','min_area') else QDoubleSpinBox()
            spin.setRange(limits[0],limits[1]);spin.setValue(limits[2]);form.addRow(title,spin);self.setting_controls[key]=spin
        self.report_dir=QLineEdit('results/vision/sessions');form.addRow('Каталог отчётов (относительно проекта)',self.report_dir)
        button(form,'Применить настройки',self.apply_settings)
        self.profile.currentIndexChanged.connect(self.profile_changed);self.profile_changed(0)
        self.log_view=QPlainTextEdit();self.log_view.setReadOnly(True)
        self.performance=PerformancePane(self)
        for widget,title in [(self.project_page,'Проект'),(self.calibrator,'Калибровка'),(self.photos_page,'Фотографии'),
            (self.video_page,'Видео'),(self.results_page,'Результаты'),(self.settings_page,'Настройки'),(self.log_view,'Журнал')]:self.tabs.addTab(widget,title)
        self.tabs.addTab(self.performance,'Производительность видео')
        self.experiment=ExperimentPane(self);self.tabs.addTab(self.experiment,'Видеоэксперимент')
        self.experiment_close_pending=False;self.experiment_close_warned=False
        bar=self.addToolBar('Проект')
        for name,callback in [('Создать',self.new_dialog),('Открыть',self.open_dialog),('Сохранить',self.save_project)]:
            action=QAction(name,self);action.triggered.connect(callback);bar.addAction(action)
        self.progress=QProgressBar();self.progress.setMaximumWidth(300);self.statusBar().addPermanentWidget(self.progress)
        self.cancel_button=QPushButton('Отмена');self.cancel_button.clicked.connect(self.cancel_job);self.statusBar().addPermanentWidget(self.cancel_button)
        self.cancel_button.setEnabled(False)
        if remember:QTimer.singleShot(0,self.offer_last_project)

    def log(self,message):
        logging.info(message);self.log_view.appendPlainText(str(message))

    def error(self,message):
        self.log(message);QMessageBox.warning(self,'GS75 RGB Vision',str(message))

    def guard(self):
        if self.active_job:
            self.statusBar().showMessage('Дождитесь операции или нажмите «Отмена»',4000);return False
        if not self.project:self.error('Сначала создайте или откройте проект');return False
        return True

    def start_job(self,function,callback):
        if self.experiment.running or self.experiment.preparing:
            self.error('Дождитесь финального OFF перед обработкой фото/видео.');return False
        if self.active_job:return False
        job=Job(function);self.active_job=job;self.progress.setRange(0,0)
        self.cancel_button.setEnabled(True);self.calibrator.setEnabled(False)
        self.job_callback=callback
        job.signals.result.connect(self.deliver_result);job.signals.error.connect(self.error)
        job.signals.cancelled.connect(self.on_cancelled)
        job.signals.progress.connect(self.job_progress);job.signals.finished.connect(self.job_finished)
        self.pool.start(job);return True

    def on_cancelled(self):self.log('Операция отменена')

    def deliver_result(self,value):
        try:self.job_callback(value)
        except Exception as exc:
            logging.exception('Result delivery failed');self.error(str(exc))

    def job_progress(self,current,total,value):
        self.performance.progress_update(current,total,value)
        self.progress.setRange(0,max(1,total));self.progress.setValue(current);self.statusBar().showMessage(f'{current} / {total}')
        if isinstance(value,dict) and 'name' in value:
            self.log(value['name']+': '+value.get('state',''))
            for rec in (value.get('records') or [{}]) if 'records' in value else []:
                row=self.batch_table.rowCount();self.batch_table.insertRow(row);self.report_rows.append(value.get('report'))
                for col,text in enumerate([value['name'],rec.get('led_id') or 'UNKNOWN',rec.get('status',value.get('state','')),rec.get('color',''),value.get('error') or value.get('registration','')]):
                    self.batch_table.setItem(row,col,QTableWidgetItem(str(text)))

    def job_finished(self):
        self.active_job=None;self.progress.setRange(0,1);self.progress.setValue(1)
        self.cancel_button.setEnabled(False);self.calibrator.setEnabled(True)
        if self.pending_result:
            path=self.pending_result;self.pending_result=None;QTimer.singleShot(0,lambda:self.result_pane.open(path))
        elif self.pending_frame is not None:
            index=self.pending_frame;self.pending_frame=None;QTimer.singleShot(0,lambda:self.request_frame(index))
        elif self.result_pane.pending_layer:
            name=self.result_pane.pending_layer;self.result_pane.pending_layer=None
            QTimer.singleShot(0,lambda:self.result_pane.show_layer(name))

    def cancel_job(self):
        self.playing=False;self.play_timer.stop()
        if self.active_job:self.active_job.cancel.set();self.log('Запрошена отмена; текущий этап OpenCV завершается безопасно')

    def refresh_recent(self):
        self.recent.clear()
        for path in self.preferences.value('recent',[]) or []:self.recent.addItem(str(path),str(path))

    def remember_project(self):
        if not self.remember:return
        previous=self.preferences.value('recent',[]) or []
        self.preferences.setValue('recent',([str(self.project.path)]+[p for p in previous if p!=str(self.project.path)])[:10]);self.refresh_recent()

    def offer_last_project(self):
        paths=self.preferences.value('recent',[]) or []
        if paths and QMessageBox.question(self,'Последний проект','Открыть '+str(paths[0])+'?')==QMessageBox.Yes:self.open_project(paths[0])

    def new_dialog(self):
        if self.active_job:return
        path,_=QFileDialog.getSaveFileName(self,'Создать проект исследования',str(ROOT/'gs75_rgb_vision_project.json'),'JSON (*.json)')
        if path:self.new_project(path)

    def new_project(self,path):
        if self.active_job or not self.calibrator.confirm_discard():return
        try:
            if self.project:self.save_project()
            self.project=ResearchProject.create(path);self.reset_calibration();self.refresh_project();self.remember_project();self.log('Создан проект '+str(path))
        except Exception as exc:self.error(str(exc))

    def reset_calibration(self):
        self.playing=False;self.play_timer.stop();self.decoder.close()
        self.video_path=self.video_image=self.video_meta=self.frame_info=self.pending_frame=None
        self.result_pane.pending_layer=None
        self.result_pane.record=None;self.result_pane.records=[];self.result_pane.table.setRowCount(0)
        self.batch_table.setRowCount(0);self.media_list.clear()
        for viewer in (self.photo_viewer,self.video_viewer,self.result_pane.viewer):
            viewer.scene().clear();viewer.image_item=None
        c=self.calibrator;c.document=None;c.project_path=None;c.selected=None;c.reference_image=None
        c.viewer.scene().clear();c.viewer.image_item=None;c.table.setRowCount(0);c.editor.setEnabled(False)
        c.root=self.project.root;c.summary.setText('Выберите эталон или карту LED');c.refresh()

    def open_dialog(self):
        if self.active_job:return
        path,_=QFileDialog.getOpenFileName(self,'Открыть проект исследования',str(ROOT),'JSON (*.json)')
        if path:self.open_project(path)

    def open_project(self,path):
        if self.active_job or not self.calibrator.confirm_discard():return
        try:
            project=ResearchProject.load(path)
            if self.project:self.save_project()
            self.project=project;self.reset_calibration();self.refresh_project();self.remember_project()
            missing=project.missing_files()
            if missing:self.error('Используйте «Найти перемещённые файлы»:\n'+'\n'.join(missing))
            if project.data.get('calibration') and not missing:self.load_calibration(project.resolve(project.data['calibration']['path']),project.root,checked=True)
        except Exception as exc:self.error(str(exc))

    def save_project(self):
        if not self.project:return False
        try:self.project.save();self.refresh_info();return True
        except Exception as exc:self.error(str(exc));return False

    def refresh_info(self):
        if not self.project:return
        p=self.project;link=p.data.get('calibration')
        self.project_info.setText(f'Проект: {p.path}\nКаталог данных: {p.root}\n'+
            (f"Карта: {link['path']} | версия {link['version']}\nЭталон: {p.data['reference']}" if link else 'Карта не выбрана. Выберите существующую карту или создайте разметку.')+
            f"\nМедиа: {len(p.data['media'])} | Опыты: {len(p.data['experiments'])}")
        suggested=self.preferences.value('last_map','') or str(ROOT/'config/gs75_board_calibration.json')
        self.suggested_map.setText('Предложенная карта (загрузка только по кнопке): '+suggested)

    def use_suggested_map(self):
        if not self.guard() or not self.calibrator.confirm_discard():return
        path=self.preferences.value('last_map','') or str(ROOT/'config/gs75_board_calibration.json')
        if not Path(path).is_file():self.choose_calibration();return
        try:
            data=calibration.load(path,verify_image=False)
            roots=[self.project.root,Path(self.preferences.value('last_map_root',str(ROOT))),ROOT]
            root=next((r for r in roots if (r/data['reference']['path']).is_file()),None)
            if root is None:self.choose_calibration();return
            self.load_calibration(path,root)
        except Exception as exc:self.error(str(exc))

    def refresh_project(self):
        self.refresh_info();self.refresh_media();self.refresh_history()
        for key,control in self.setting_controls.items():control.setValue(self.project.data['settings'][key])
        self.analysis_mode.setCurrentText(self.project.data['settings']['mode']);self.report_dir.setText(self.project.data['reports_dir'])
        if any(self.project.data['settings'][k]!=DEFAULTS[k] for k in self.setting_controls):self.profile.setCurrentIndex(1)

    def relink_files(self):
        if not self.guard():return
        for old in self.project.missing_files():
            path,_=QFileDialog.getOpenFileName(self,'Найти '+old,str(self.project.path.parent))
            if path:
                try:self.project.relocate(old,path)
                except Exception as exc:self.error(str(exc))
        self.save_project()
        if self.project.data.get('calibration') and not self.project.missing_files():self.load_calibration(self.project.resolve(self.project.data['calibration']['path']),self.project.root,True)

    def choose_calibration(self):
        if not self.guard() or not self.calibrator.confirm_discard():return
        path,_=QFileDialog.getOpenFileName(self,'Выбрать карту LED',str(ROOT/'config'),'JSON (*.json)')
        if not path:return
        try:
            data=calibration.load(path,verify_image=False)
            roots=[self.project.root,ROOT,Path(path).parent,Path(path).parent.parent]
            root=next((r for r in roots if (r/data['reference']['path']).is_file()),None)
            if root is None:
                value=QFileDialog.getExistingDirectory(self,'Выберите корень данных с '+data['reference']['path'])
                if not value:return
                root=Path(value)
            self.load_calibration(path,root)
        except Exception as exc:self.error(str(exc))

    def bind_saved_map(self):
        p=self.project;c=self.calibrator;data=c.document.data
        p.data.update(data_root=p.relative(c.root),calibration=dict(path=p.relative(c.project_path),
            sha256=image_hash(c.project_path),version=data['calibration_version']),reference=p.relative(c.root/data['reference']['path']))
        if self.remember:
            self.preferences.setValue('last_map',str(c.project_path));self.preferences.setValue('last_map_root',str(c.root))

    def load_calibration(self,path,root,checked=False):
        draft=Path(str(path)+'.autosave.json');recover=False
        if draft.exists() and Path(path).exists() and draft.stat().st_mtime>Path(path).stat().st_mtime:
            recover=QMessageBox.question(self,'Черновик карты','Есть более новое autosave. Восстановить его?')==QMessageBox.Yes
        def work(cancel,progress):
            if checked:self.project.checked_calibration()
            data=calibration.load(draft if recover else path,root);checkpoint(cancel)
            return data,read_image(Path(root)/data['reference']['path'],data.get('camera_model'))
        def done(value):
            data,image=value;c=self.calibrator;c.root=Path(root);c.document=calibration.Document(data)
            if not recover:c.document.mark_saved()
            c.reference_image=image;c.project_path=Path(path);c.selected=None;c.viewer.set_image(image);c.refresh()
            if not recover:self.bind_saved_map()
            self.save_project();self.log('Восстановлен черновик: сохраните карту' if recover else 'Карта загружена: '+str(path))
        self.start_job(work,done)

    def choose_reference(self):
        if not self.guard() or not self.calibrator.confirm_discard():return
        path,_=QFileDialog.getOpenFileName(self,'Выберите эталон','','Images (*.jpg *.jpeg *.png *.tif *.tiff)')
        if path:self.set_reference(path)

    def set_reference(self,path):
        root=self.project.root
        def done(value):
            data,image=value;c=self.calibrator;c.root=root;c.document=calibration.Document(data);c.project_path=None
            c.reference_image=image;c.selected=None;c.viewer.set_image(image);c.refresh()
            self.project.data['calibration']=None;self.project.data['reference']=self.project.relative(root/data['reference']['path'])
            self.save_project();self.tabs.setCurrentWidget(c)
        self.start_job(lambda cancel,progress:calibration.create(path,root,self.calibrator.camera),done)

    def import_dialog(self):
        if not self.guard():return
        initial=self.project.resolve(self.project.data.get('last_import') or '.')
        paths,_=QFileDialog.getOpenFileNames(self,'Добавить фотографии',str(initial),'Images (*.jpg *.jpeg *.png *.tif *.tiff)')
        if paths:self.import_paths(paths)

    def import_paths(self,paths):
        if not self.guard():return
        def work(cancel,progress):
            imported=[];errors=[]
            for index,path in enumerate(paths):
                if cancel.is_set():break
                try:
                    path=Path(path)
                    if path.suffix.lower() not in PHOTO_EXTENSIONS|VIDEO_EXTENSIONS:raise ValueError('Неподдерживаемый формат')
                    thumb=None
                    if path.suffix.lower() in PHOTO_EXTENSIONS:
                        with Image.open(path) as im:
                            im.draft('RGB',(160,120));im=ImageOps.exif_transpose(im);im.thumbnail((110,80));thumb=im.convert('RGB').copy()
                    elif not path.is_file():raise FileNotFoundError(path)
                    imported.append((str(path),thumb))
                except Exception as exc:errors.append(f'{path}: {exc}')
                progress(index+1,len(paths),{})
            return imported,errors
        def done(value):
            imported,errors=value;icons={}
            for path,thumb in imported:
                media=self.project.add_media(path)
                if thumb:
                    raw=thumb.tobytes();image=QImage(raw,thumb.width,thumb.height,thumb.width*3,QImage.Format_RGB888).copy()
                    target=self.project.path.parent/'data/thumbnails'/(media['id']+'.png');target.parent.mkdir(parents=True,exist_ok=True)
                    if not image.save(str(target)):raise OSError('Не удалось сохранить миниатюру')
                    media['metadata']['thumbnail']=self.project.relative(target);icons[media['id']]=QIcon(QPixmap.fromImage(image))
            self.refresh_media(icons);self.save_project()
            if errors:self.error('\n'.join(errors))
        self.start_job(work,done)

    def refresh_media(self,new_icons=None):
        icons={self.media_list.item(i).data(Qt.UserRole):self.media_list.item(i).icon() for i in range(self.media_list.count())}
        icons.update(new_icons or {});self.media_list.clear()
        if not self.project:return
        for media in self.project.data['media']:
            item=QListWidgetItem(f"{media['role']} | {media['name']}"+(' [видео]' if media['kind']=='video' else ''))
            item.setData(Qt.UserRole,media['id']);item.setToolTip(str(self.project.resolve(media['path'])))
            thumbnail=media['metadata'].get('thumbnail')
            item.setIcon(icons.get(media['id'],QIcon(str(self.project.resolve(thumbnail))) if thumbnail else QIcon()));self.media_list.addItem(item)

    def selected_media(self):return [self.project.media(item.data(Qt.UserRole)) for item in self.media_list.selectedItems()]

    def assign_selected(self):
        if not self.guard():return
        selected=self.selected_media();role=self.role.currentText()
        if role in ('OFF','REFERENCE') and len(selected)!=1:self.error('Для OFF или REFERENCE выберите ровно одно фото');return
        try:
            if role=='REFERENCE':
                if not self.calibrator.confirm_discard():return
                self.set_reference(self.project.resolve(selected[0]['path']))
            for media in selected:self.project.assign(media['id'],role)
            self.refresh_media();self.save_project()
        except Exception as exc:self.error(str(exc))

    def media_menu(self,point):
        menu=QMenu(self)
        for role in ('REFERENCE','OFF','ON','UNASSIGNED'):menu.addAction(role,lambda r=role:(self.role.setCurrentText(r),self.assign_selected()))
        menu.exec(self.media_list.mapToGlobal(point))

    def preview_media(self,item):
        if not self.guard():return
        media=self.project.media(item.data(Qt.UserRole));path=self.project.resolve(media['path'])
        if media['kind']=='video':self.open_video(path);return
        self.start_job(lambda cancel,progress:read_image(path),self.photo_viewer.set_image)

    def compare_selected(self):
        if not self.guard():return
        paths=[self.project.resolve(m['path']) for m in self.selected_media() if m['kind']=='photo']
        if len(paths)!=2:self.error('Выберите два фото для сравнения');return
        def work(cancel,progress):
            import cv2,numpy as np
            panels=[]
            for path in paths:
                im=read_image(path);checkpoint(cancel);scale=min(1,1200/im.shape[0]);im=cv2.resize(im,(round(im.shape[1]*scale),round(im.shape[0]*scale)))
                panel=np.zeros((1200,im.shape[1],3),np.uint8);panel[:im.shape[0]]=im;panels.append(panel)
            return np.concatenate(panels,axis=1)
        self.start_job(work,self.photo_viewer.set_image)

    def analyze_selected(self):
        if not self.guard():return
        if self.calibrator.document and self.calibrator.document.dirty:self.error('Сначала сохраните изменения карты');return
        off=[m for m in self.project.data['media'] if m['role']=='OFF'];selected=[m for m in self.selected_media() if m['role']=='ON']
        if not selected:selected=[m for m in self.project.data['media'] if m['role']=='ON']
        if len(off)!=1 or not selected:self.error('Назначьте один OFF и один или несколько ON');return
        self.project.data['settings']['mode']=self.analysis_mode.currentText();self.run_batch(off[0]['id'],[m['id'] for m in selected])

    def run_batch(self,off_id,on_ids):
        if not self.guard():return
        self.save_project();snapshot=ResearchProject(self.project.path,deepcopy(self.project.data))
        self.batch_table.setRowCount(0);self.report_rows=[]
        def done(experiment):
            self.project.data['experiments'].append(experiment);self.save_project();self.refresh_history();self.show_experiment(experiment)
            self.tabs.setCurrentWidget(self.results_page);self.log('Пакет: '+experiment['state'])
        self.start_job(lambda cancel,progress:batch(snapshot,off_id,on_ids,cancel,progress),done)

    def refresh_history(self):
        self.history.clear()
        if self.project:
            for e in self.project.data['experiments']:self.history.addItem(e['name']+' | '+e['state'],e['id'])
            if self.history.count():self.history.setCurrentIndex(self.history.count()-1)

    def selected_experiment(self):return next((e for e in self.project.data['experiments'] if e['id']==self.history.currentData()),None)

    def open_history(self):
        if self.guard() and self.selected_experiment():self.show_experiment(self.selected_experiment())

    def show_experiment(self,experiment):
        self.fill_batch_table([experiment])
        first=next((self.project.resolve(i['report']) for i in experiment['items'] if (self.project.resolve(i['report'])/'results.json').is_file()),None)
        if first:
            if self.active_job:self.pending_result=first
            else:self.result_pane.open(first)

    def fill_batch_table(self,experiments):
        self.batch_table.setRowCount(0);self.report_rows=[]
        for e in experiments:
            if not e:continue
            for item in e['items']:
                for rec in item['records'] or [{}]:
                    row=self.batch_table.rowCount();self.batch_table.insertRow(row);self.report_rows.append(item.get('report'))
                    name=(e['name']+' / ' if len(experiments)>1 else '')+item['name']
                    for col,value in enumerate([name,rec.get('led_id') or 'UNKNOWN',rec.get('status',item['state']),rec.get('color',''),item.get('error') or item.get('registration','')]):
                        self.batch_table.setItem(row,col,QTableWidgetItem(str(value)))

    def open_report_row(self,row,column):
        if not self.guard():return
        try:self.result_pane.open(self.project.resolve(self.report_rows[row]))
        except Exception as exc:self.error(str(exc))

    def rename_history(self):
        if not self.guard():return
        e=self.selected_experiment()
        if e:
            name,ok=QInputDialog.getText(self,'Название опыта','Название',text=e['name'])
            if ok and name.strip():e['name']=name.strip();self.save_project();self.refresh_history()

    def repeat_history(self):
        if not self.guard():return
        e=self.selected_experiment()
        if e:self.run_batch(*self.project.repeat_plan(e))

    def export_history(self):
        if not self.guard():return
        e=self.selected_experiment()
        if not e:return
        dest=QFileDialog.getExistingDirectory(self,'Каталог экспорта')
        if not dest:return
        target=Path(dest)/e['id']
        def work(cancel,progress):
            if target.exists():raise FileExistsError('Каталог экспорта уже существует; выберите новый')
            shutil.copytree(self.project.resolve(e['report']),target);return str(target)
        self.start_job(work,lambda path:self.log('Экспорт: '+path))

    def compare_runs(self):
        if not self.guard():return
        experiments=self.project.data['experiments']
        if len(experiments)<2:self.error('Нужны минимум два опыта');return
        labels=[f"{i+1}: {e['name']}" for i,e in enumerate(experiments)]
        label,ok=QInputDialog.getItem(self,'Сравнить с выбранным опытом','Другой опыт',labels,editable=False)
        if ok:self.fill_batch_table([self.selected_experiment(),experiments[labels.index(label)]])

    def profile_changed(self,index):
        for key,control in self.setting_controls.items():
            control.setEnabled(index==1)
            if index==0:control.setValue(DEFAULTS[key])

    def apply_settings(self):
        if not self.guard():return
        settings={key:control.value() for key,control in self.setting_controls.items()}
        if settings['dominance_ratio']>=settings['mixed_ratio']:self.error('Порог доминирования должен быть меньше порога смеси');return
        self.project.data['settings'].update(settings,mode=self.analysis_mode.currentText())
        self.project.data['reports_dir']=self.report_dir.text().strip() or 'results/vision/sessions';self.save_project();self.log('Настройки сохранены')

    def video_dialog(self):
        if not self.guard():return
        path,_=QFileDialog.getOpenFileName(self,'Открыть видео','','Video (*.mp4 *.mov *.avi)')
        if path:self.open_video(path)

    def open_video(self,path):
        if self.active_job:return
        self.playing=False;self.play_timer.stop()
        self.video_meta=self.frame_info=self.video_image=None
        def work(cancel,progress):
            meta=self.decoder.open(path);checkpoint(cancel);image,info=self.decoder.frame(0);return meta,image,info
        def done(value):
            self.video_meta,image,info=value;self.video_path=Path(path)
            if self.project:self.project.add_media(path);self.save_project();self.refresh_media()
            self.video_slider.setRange(0,max(0,self.video_meta['frame_count']-1));self.display_frame((image,info));self.tabs.setCurrentWidget(self.video_page)
        self.start_job(work,done)

    def display_frame(self,value):
        self.video_image,self.frame_info=value;self.video_viewer.set_image(self.video_image);self.video_slider.setValue(self.frame_info['frame_index'])
        timestamp=self.frame_info['timestamp_ms'];stamp=f'{timestamp/1000:.3f} с (декодер)' if timestamp is not None else 'точное время неизвестно'
        self.video_label.setText(f"Кадр {self.frame_info['frame_index']} / {self.video_meta['frame_count']} | {stamp} | VFR: FPS только ориентир")

    def request_frame(self,index):
        if not self.video_meta:return
        if self.active_job:self.pending_frame=index;return
        self.start_job(lambda cancel,progress:self.decoder.frame(index),self.display_frame)

    def step_video(self,step):
        if self.frame_info:self.playing=False;self.play_timer.stop();self.request_frame(max(0,self.frame_info['frame_index']+step))

    def play_pause(self):
        if not self.video_meta:return
        self.playing=not self.playing
        if self.playing:self.play_timer.start(max(20,round(1000/(self.video_meta['fps'] or 25))))
        else:self.play_timer.stop()

    def advance_video(self):
        if not self.playing or self.active_job or not self.frame_info:return
        index=self.frame_info['frame_index']+1
        if self.video_meta['frame_count'] and index>=self.video_meta['frame_count']:self.playing=False;self.play_timer.stop();return
        self.request_frame(index)

    def use_frame(self,role):
        if not self.guard() or self.video_image is None:return
        self.playing=False;self.play_timer.stop();image=self.video_image.copy();info=deepcopy(self.frame_info);video=self.video_path
        snapshot=ResearchProject(self.project.path,deepcopy(self.project.data))
        def done(media):
            self.project.data['media'].append(media)
            if role=='OFF':self.project.assign(media['id'],'OFF')
            self.save_project();self.refresh_media();self.log('Кадр добавлен как '+role)
        self.start_job(lambda cancel,progress:snapshot.capture_frame(image,video,info,role),done)

    def save_frame_dialog(self):
        if not self.guard() or self.video_image is None:return
        path,_=QFileDialog.getSaveFileName(self,'Сохранить кадр','','PNG (*.png)')
        if not path:return
        image=self.video_image.copy();self.start_job(lambda cancel,progress:write_image(path,image),lambda _:self.log('Кадр сохранён: '+path))

    def closeEvent(self,event):
        worker=self.experiment.worker
        if worker.isRunning():
            if not self.experiment_close_pending:
                self.experiment_close_pending=True;self.experiment.ready=False
                self.experiment.outcome.setText('Закрытие: сценарий прерывается, отправляется OFF.')
                worker.shutdown()
            event.ignore();QTimer.singleShot(50,self.close);return
        if worker.ever_connected and not worker.last_off_confirmed and not self.experiment_close_warned:
            self.experiment_close_warned=True
            QMessageBox.warning(self,'OFF не подтверждён','Физическое состояние выходов неизвестно. Снимите питание STM32. IWDG выключен.')
        if self.active_job:
            self.experiment_close_pending=False
            self.cancel_job();QMessageBox.information(self,'Завершение операции','Отмена запрошена. Дождитесь завершения текущего этапа и закройте окно снова.');event.ignore();return
        if not self.calibrator.confirm_discard():self.experiment_close_pending=False;event.ignore();return
        self.play_timer.stop();self.decoder.close()
        if self.project:self.save_project()
        self.pool.waitForDone();event.accept()
