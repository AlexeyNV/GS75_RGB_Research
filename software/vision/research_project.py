"""Research session persistence. Calibration schema stays independent and compatible."""
from copy import deepcopy
from datetime import datetime, timezone
import csv
import json
import os
from pathlib import Path
import threading
import uuid
from . import calibration
from .project_storage import atomic_json, image_hash, read_image, write_image
from .led_detection import analyze_paths, export

DEFAULTS = dict(mode='KNOWN_LEDS',threshold=30,color_threshold=25,roi_radius=40,
                min_area=6,registration_error=3.,dominance_ratio=.45,mixed_ratio=.70)
PHOTO_EXTENSIONS = {'.jpg','.jpeg','.png','.tif','.tiff'}
VIDEO_EXTENSIONS = {'.mp4','.mov','.avi'}
LAYERS = {'ON markers':'on_markers.png','Registered OFF':'registered_off.png',
          'Registered ON':'registered_on.png','Difference':'difference.png',
          'Valid overlap':'valid_overlap.png','Detected LEDs':'annotated.png',
          'Original ON annotated':'original_on_annotated.png','Color mask':'color_mask.png',
          'Color signal':'color_signal.png','Candidates':'candidates.png',
          'Accepted':'accepted.png','Rejected':'rejected_candidates.png','LED ROIs':'led_rois.png'}


def utc():
    return datetime.now(timezone.utc).isoformat()


class Cancelled(RuntimeError):
    pass


def checkpoint(cancel):
    if cancel.is_set():
        raise Cancelled('Обработка отменена')


class ResearchProject:
    def __init__(self, path, data):
        self.path = Path(path).resolve()
        self.data = data

    @classmethod
    def create(cls, path, root=None):
        path = Path(path).resolve()
        if path.exists():
            raise FileExistsError('Файл проекта уже существует')
        project = cls(path, dict(schema_version=1,application='GS75 RGB Vision',
            id=uuid.uuid4().hex,name=path.parent.name,created_utc=utc(),
            data_root='',calibration=None,reference=None,media=[],experiments=[],
            settings=deepcopy(DEFAULTS),last_import='',reports_dir='results/vision/sessions'))
        project.data['data_root'] = project.relative(root or path.parent)
        project.save()
        return project

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if data.get('application')!='GS75 RGB Vision' or data.get('schema_version')!=1:
            raise ValueError('Это не поддерживаемый проект GS75 RGB Vision')
        for key in ('media','experiments'):
            if not isinstance(data.get(key),list):
                raise ValueError('Некорректный список '+key)
        if not isinstance(data.get('settings'),dict):
            raise ValueError('Некорректные настройки проекта')
        project=cls(path,data)
        project.data['settings']={**DEFAULTS,**data['settings']}
        if len({m['id'] for m in data['media']})!=len(data['media']):
            raise ValueError('Повторяющиеся ID медиа')
        return project

    def relative(self, path):
        try:
            return Path(os.path.relpath(Path(path).resolve(),self.path.parent)).as_posix()
        except ValueError:  # Windows different drives: preserve an explicit absolute link.
            return str(Path(path).resolve())

    def resolve(self, value):
        return (self.path.parent/Path(value)).resolve()

    @property
    def root(self):
        return self.resolve(self.data['data_root'])

    def save(self):
        atomic_json(self.path,self.data)

    def bind_calibration(self, path, root):
        data=calibration.load(path,root)
        self.data.update(data_root=self.relative(root),
            calibration=dict(path=self.relative(path),sha256=image_hash(path),
                version=data['calibration_version']),
            reference=self.relative(Path(root)/data['reference']['path']))
        return data

    def checked_calibration(self):
        link=self.data.get('calibration')
        if not link:
            raise ValueError('Выберите карту во вкладке «Калибровка» и сохраните проект')
        path=self.resolve(link['path'])
        if image_hash(path)!=link['sha256']:
            raise ValueError('Карта изменена вне проекта. Откройте и явно подтвердите нужную карту')
        data=calibration.load(path,self.root)
        if data['calibration_version']!=link['version']:
            raise ValueError('Версия калибровки изменилась')
        return data

    def missing_files(self):
        links=[m['path'] for m in self.data['media']]
        if self.data.get('calibration'):
            links += [self.data['calibration']['path'],self.data['reference']]
        return [link for link in links if not self.resolve(link).is_file()]

    def add_media(self,path,role='UNASSIGNED',metadata=None):
        path=Path(path).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if role not in ('REFERENCE','OFF','ON','UNASSIGNED'):
            raise ValueError('Некорректная роль')
        kind='video' if path.suffix.lower() in VIDEO_EXTENSIONS else 'photo'
        if kind=='photo' and path.suffix.lower() not in PHOTO_EXTENSIONS:
            raise ValueError('Неподдерживаемый файл: '+path.name)
        existing=next((m for m in self.data['media'] if self.resolve(m['path'])==path),None)
        if existing:
            return existing
        media=dict(id=uuid.uuid4().hex,path=self.relative(path),kind=kind,role='UNASSIGNED',
                   name=path.name,metadata=metadata or {})
        self.data['media'].append(media)
        self.data['last_import']=self.relative(path.parent)
        self.assign(media['id'],role)
        return media

    def assign(self, identifier, role):
        if role not in ('REFERENCE','OFF','ON','UNASSIGNED'):
            raise ValueError('Некорректная роль')
        media=self.media(identifier)
        if media['kind']=='video' and role!='UNASSIGNED':
            raise ValueError('Назначьте роль выбранному кадру, а не всему видео')
        if role in ('OFF','REFERENCE'):
            for item in self.data['media']:
                if item['role']==role:
                    item['role']='UNASSIGNED'
        media['role']=role

    def media(self, identifier):
        return next(m for m in self.data['media'] if m['id']==identifier)

    def capture_frame(self, image, video, frame, role):
        path=self.root/'data/captures'/('frame_'+uuid.uuid4().hex+'.png')
        write_image(path,image)
        metadata=dict(video_path=self.relative(video),**frame)
        return self.add_media(path,role,metadata)

    def relocate(self, old, new):
        new=Path(new).resolve()
        if not new.is_file():
            raise FileNotFoundError(new)
        relative=self.relative(new)
        for item in self.data['media']:
            if item['path']==old:
                item['path']=relative
        if self.data.get('calibration') and self.data['calibration']['path']==old:
            if image_hash(new)!=self.data['calibration']['sha256']:
                raise ValueError('Выбранная карта отличается. Подтвердите её через Калибровку')
            self.data['calibration']['path']=relative
        if self.data.get('reference')==old:
            data=calibration.load(self.resolve(self.data['calibration']['path']),self.root,False)
            if image_hash(new)!=data['reference']['sha256']:
                raise ValueError('Контрольная сумма эталона отличается')
            expected=Path(data['reference']['path'])
            root=new
            for _ in expected.parts:
                root=root.parent
            if (root/expected).resolve()!=new:
                raise ValueError('Сохраните относительный путь эталона '+expected.as_posix())
            self.data['data_root']=self.relative(root)
            self.data['reference']=relative

    def repeat_plan(self, experiment):
        return experiment['off_id'],experiment['on_ids']


def batch(project, off_id, on_ids, cancel=None, notify=lambda *args:None):
    """Sequential full-resolution jobs; images are released after each exported report."""
    cancel=cancel or threading.Event()
    checkpoint(cancel)
    data=project.checked_calibration()
    settings=deepcopy(project.data['settings'])
    off=project.media(off_id)
    if off['kind']!='photo' or not on_ids:
        raise ValueError('Нужен один OFF и хотя бы один ON')
    experiment=dict(id=uuid.uuid4().hex,name='Опыт '+utc(),created_utc=utc(),
        off_id=off_id,on_ids=list(on_ids),settings=settings,calibration_version=data['calibration_version'],
        items=[],state='RUNNING')
    folder=project.resolve(project.data['reports_dir'])/experiment['id']
    folder.mkdir(parents=True,exist_ok=False)
    experiment['report']=project.relative(folder)
    try:
        for index,on_id in enumerate(on_ids):
            checkpoint(cancel)
            media=project.media(on_id)
            if media['kind']!='photo':
                raise ValueError('Для анализа выберите фото или извлечённый кадр')
            output=folder/(str(index+1).zfill(3)+'_'+media['id'])
            item=dict(media_id=on_id,name=media['name'],report=project.relative(output))
            try:
                a=analyze_paths(data,project.resolve(off['path']),project.resolve(media['path']),
                    experiment['id'],cancel_check=lambda:checkpoint(cancel),**settings)
                checkpoint(cancel)
                export(a,output)
                # Persist a snapshot of the exact map, never mutate the user's map.
                atomic_json(output/'calibration_snapshot.json',data)
                a.result['sources']=dict(off=off['path'],on=media['path'],off_id=off['id'],on_id=media['id'],
                    off_metadata=off['metadata'],on_metadata=media['metadata'])
                atomic_json(output/'results.json',a.result)
                records=a.result['known_leds'] if settings['mode']=='KNOWN_LEDS' else a.result['detections']
                item.update(state=a.result['analysis_status'],registration=a.result['registration_status'],
                            records=deepcopy(records),warnings=a.result['warnings'])
                del a
            except Cancelled:
                raise
            except Exception as exc:
                item.update(state='ERROR',error=str(exc),records=[])
            experiment['items'].append(item)
            atomic_json(folder/'batch.json',experiment)
            notify(index+1,len(on_ids),deepcopy(item))
        experiment['state']='COMPLETED_WITH_ERRORS' if any(i['state'] in ('ERROR','FAILED') for i in experiment['items']) else 'COMPLETED'
    except Cancelled:
        experiment['state']='CANCELLED'
    finally:
        atomic_json(folder/'batch.json',experiment)
        columns=['file','led_id','status','color','registration','brightness','chroma','color_confidence','error']
        with (folder/'batch.csv').open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=columns); writer.writeheader()
            for item in experiment['items']:
                for record in item['records'] or [{}]:
                    writer.writerow({**{k:record.get(k) for k in columns if k not in ('file','registration','error')},
                                     'file':item['name'],'registration':item.get('registration'),
                                     'error':item.get('error')})
    return experiment
