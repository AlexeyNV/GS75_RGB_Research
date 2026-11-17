"""Sequential PyAV decoding for benchmarks; real PTS/time_base, no frame skipping."""
from pathlib import Path
import av
import cv2


def orient_frame(image, rotation):
    """PyAV rotation is counterclockwise; preserve timestamps and rotate pixels once."""
    angle=int(rotation) % 360
    if angle not in (0,90,180,270):raise ValueError('Unsupported non-right-angle video display rotation')
    return image if angle==0 else cv2.rotate(image,{90:cv2.ROTATE_90_COUNTERCLOCKWISE,
        180:cv2.ROTATE_180,270:cv2.ROTATE_90_CLOCKWISE}[angle])


class SequentialVideoReader:
    def __init__(self):self.container=None;self.iterator=None;self.index=0
    def open(self,path):
        self.close();self.container=av.open(str(path));self.stream=self.container.streams.video[0]
        self.stream.thread_type='AUTO';self.iterator=self.container.decode(self.stream);self.index=0
        self.fps=float(self.stream.average_rate) if self.stream.average_rate else None
        self.count=self.stream.frames or 0
        duration=float(self.stream.duration*self.stream.time_base) if self.stream.duration is not None else (
            self.container.duration/av.time_base if self.container.duration else None)
        self.metadata=dict(path=str(Path(path)),width=self.stream.codec_context.width,height=self.stream.codec_context.height,
            coded_width=self.stream.codec_context.width,coded_height=self.stream.codec_context.height,rotation_degrees=None,
            stream_start_pts=self.stream.start_time,stream_time_base=str(self.stream.time_base),
            container_duration_s=self.container.duration/av.time_base if self.container.duration else None,
            stream_start_s=float(self.stream.start_time*self.stream.time_base) if self.stream.start_time is not None else None,
            fps=self.fps,frame_count=self.count,duration_s=duration,backend='PyAV',av=av.__version__,
            codec=self.stream.codec_context.name,timestamps='frame.pts * frame.time_base; FPS fallback explicitly estimated')
        return self.metadata
    def frame(self,index):
        if index!=self.index:raise ValueError('Benchmark reader is sequential: no seek or skipped frames')
        frame=next(self.iterator);actual=self.index;self.index+=1
        timestamp=float(frame.pts*frame.time_base)*1000 if frame.pts is not None and frame.time_base else None
        rotation=frame.rotation
        image=orient_frame(frame.to_ndarray(format='bgr24'),rotation)
        self.metadata.update(rotation_degrees=rotation,width=image.shape[1],height=image.shape[0])
        return image,dict(frame_index=actual,pts=frame.pts,rotation_degrees=rotation,
            time_base=str(frame.time_base) if frame.time_base else None,timestamp_ms=timestamp,
            timestamp_source='pts' if timestamp is not None else 'unknown',
            estimated_ms=actual*1000/self.fps if self.fps else None)
    def close(self):
        if self.container is not None:self.container.close()
        self.container=self.iterator=None
