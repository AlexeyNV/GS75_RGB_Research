"""Reference external MP4/MOV; read metadata in a worker, never copy media."""
import json
from pathlib import Path
import av
from .journal import save_session, utc_now


def attach_video(session_path, video_path):
    session_path, video_path = Path(session_path), Path(video_path).resolve()
    if video_path.suffix.lower() not in ('.mp4', '.mov'):
        raise ValueError('Choose MP4 or MOV')
    data = json.loads((session_path/'session.json').read_text(encoding='utf-8'))
    if data['status'] not in ('COMPLETED', 'FAILED', 'ABORTED'):
        raise ValueError('Finish experiment before importing video')
    stat = video_path.stat()
    with av.open(str(video_path)) as container:
        stream = container.streams.video[0]
        duration = float(stream.duration*stream.time_base) if stream.duration is not None else (
            container.duration/av.time_base if container.duration else None)
        first = next(container.decode(stream), None)
        video = dict(path=str(video_path), size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns,
            width=stream.codec_context.width, height=stream.codec_context.height,
            fps=float(stream.average_rate) if stream.average_rate else None, duration_s=duration,
            time_base=str(stream.time_base), stream_start_pts=stream.start_time,
            first_frame_pts=first.pts if first else None,
            first_frame_time_base=str(first.time_base) if first else None,
            container_metadata=dict(container.metadata), stream_metadata=dict(stream.metadata),
            checksum=None, checksum_reason='Not computed: external large media; size/mtime recorded, no GUI blocking hash',
            attached_utc=utc_now(), optical_alignment='UNALIGNED')
    data.setdefault('video_history', []).append(video)
    data['video'] = video
    data['synchronization'].update(status='UNALIGNED', offset_ms=None, uncertainty_ms=None)
    save_session(session_path, data)
    return video
