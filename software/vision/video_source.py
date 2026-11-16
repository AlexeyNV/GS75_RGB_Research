"""Bounded-memory offline video reader. No hardware camera or assumed global homography."""
from pathlib import Path
import math
import cv2


class VideoReader:
    def __init__(self):
        self.capture=None
        self.path=None

    def close(self):
        if self.capture is not None:
            self.capture.release()
        self.capture=None

    def open(self,path):
        self.close()
        self.path=Path(path)
        self.capture=cv2.VideoCapture(str(path))
        if not self.capture.isOpened():
            self.close()
            raise ValueError('Не удалось открыть видео: нет файла или подходящего декодера')
        self.count=max(0,int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        self.fps=float(self.capture.get(cv2.CAP_PROP_FPS))
        if not math.isfinite(self.fps) or self.fps<=0:
            self.fps=None
        return dict(path=str(self.path),frame_count=self.count,fps=self.fps,
                    timing='Время декодера; при VFR FPS не определяет точное время кадра')

    def frame(self,index):
        if self.capture is None:
            raise ValueError('Сначала откройте видео')
        index=max(0,int(index))
        if self.count and index>=self.count:
            raise IndexError('Кадр вне диапазона')
        position=int(self.capture.get(cv2.CAP_PROP_POS_FRAMES))
        if position!=index and not self.capture.set(cv2.CAP_PROP_POS_FRAMES,index):
            raise ValueError('Декодер не поддерживает эту перемотку')
        ok,image=self.capture.read()
        if not ok:
            raise ValueError('Кадр недоступен или достигнут конец видео')
        actual=max(0,round(self.capture.get(cv2.CAP_PROP_POS_FRAMES))-1)
        milliseconds=float(self.capture.get(cv2.CAP_PROP_POS_MSEC))
        reported=math.isfinite(milliseconds) and milliseconds>=0 and (actual==0 or milliseconds>0)
        return image,dict(frame_index=actual,requested_index=index,
            timestamp_ms=milliseconds if reported else None,
            timestamp_source='decoder_reported' if reported else 'unknown',
            estimated_ms=actual*1000/self.fps if self.fps else None,
            timing_warning='Декодер может выполнять keyframe seek; время не является подтверждённым аппаратным timestamp')
