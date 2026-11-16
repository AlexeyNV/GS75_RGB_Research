"""Sequential PyAV decoding for benchmarks; real PTS/time_base, no frame skipping."""
from pathlib import Path
import av


class SequentialVideoReader:
    def __init__(self):self.container=None;self.iterator=None;self.index=0
    def open(self,path):
        self.close();self.container=av.open(str(path));self.stream=self.container.streams.video[0]
        self.stream.thread_type='AUTO';self.iterator=self.container.decode(self.stream);self.index=0
        self.fps=float(self.stream.average_rate) if self.stream.average_rate else None
        self.count=self.stream.frames or 0
        duration=float(self.stream.duration*self.stream.time_base) if self.stream.duration is not None else (
            self.container.duration/av.time_base if self.container.duration else None)
        return dict(path=str(Path(path)),width=self.stream.codec_context.width,height=self.stream.codec_context.height,
            fps=self.fps,frame_count=self.count,duration_s=duration,backend='PyAV',av=av.__version__,
            codec=self.stream.codec_context.name,timestamps='frame.pts * frame.time_base; FPS fallback explicitly estimated')
    def frame(self,index):
        if index!=self.index:raise ValueError('Benchmark reader is sequential: no seek or skipped frames')
        frame=next(self.iterator);actual=self.index;self.index+=1
        timestamp=float(frame.pts*frame.time_base)*1000 if frame.pts is not None and frame.time_base else None
        return frame.to_ndarray(format='bgr24'),dict(frame_index=actual,pts=frame.pts,
            time_base=str(frame.time_base) if frame.time_base else None,timestamp_ms=timestamp,
            timestamp_source='pts' if timestamp is not None else 'unknown',
            estimated_ms=actual*1000/self.fps if self.fps else None)
    def close(self):
        if self.container is not None:self.container.close()
        self.container=self.iterator=None
