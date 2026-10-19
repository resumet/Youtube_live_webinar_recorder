from threading import Event

from youtube_live_recorder.bootstrap import ApplicationContext
from youtube_live_recorder.core.recording_manager import RecordingManager
from youtube_live_recorder.core.scheduler import Scheduler
from youtube_live_recorder.services.ffmpeg_adapter import FFmpegAdapter
from youtube_live_recorder.services.ffprobe_adapter import FFprobeAdapter
from youtube_live_recorder.services.toolchain import Toolchain
from youtube_live_recorder.services.ytdlp_adapter import YtdlpAdapter
from youtube_live_recorder.utils.instance_lock import InstanceLock


class Engine:
    def __init__(self, context: ApplicationContext) -> None:
        self.context = context
        tools = Toolchain.discover()
        self.metadata = YtdlpAdapter(tools)
        self.recordings = RecordingManager(
            context.repository,
            context.settings,
            self.metadata,
            self.metadata,
            FFmpegAdapter(tools.ffmpeg, FFprobeAdapter(tools.ffprobe)),
        )
        self.scheduler = Scheduler(context.repository, self.metadata, self.recordings)
        self.stop_event = Event()
        self.instance = InstanceLock(context.paths.root / "engine.lock")

    def run(self) -> None:
        with self.instance:
            if self.context.repository.active_session():
                raise RuntimeError(
                    "미완료 작업이 있습니다. 자동 파일 복구는 후속 단계에서 연결됩니다."
                )
            try:
                self.scheduler.run(self.stop_event)
            finally:
                self.recordings.shutdown()

    def stop(self) -> None:
        self.stop_event.set()
        self.recordings.stop_accepting()
