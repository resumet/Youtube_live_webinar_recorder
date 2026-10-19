from threading import Event

from youtube_live_recorder.bootstrap import ApplicationContext
from youtube_live_recorder.core.recording_manager import RecordingManager
from youtube_live_recorder.core.recovery_manager import RecoveryManager
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
            try:
                self.scheduler.power.set_required(True)
                RecoveryManager(
                    self.context.repository, self.context.settings, self.recordings.finalizer
                ).run(self.stop_event)
                # 일반 대기 항목도 재시작 직후 현재 방송 상태를 재검증한다.
                from youtube_live_recorder.data.models import BroadcastStatus as B
                from youtube_live_recorder.utils.time import to_iso, utc_now

                for item in self.context.repository.list_broadcasts():
                    if item.status in {B.WAITING, B.LIVE_DETECTED, B.ERROR_RETRYABLE}:
                        self.context.repository.set_next_check(item.id, to_iso(utc_now()))
                self.scheduler.run(self.stop_event)
            finally:
                self.recordings.shutdown()
                self.scheduler.power.close()

    def stop(self) -> None:
        self.stop_event.set()
        self.recordings.stop_accepting()
