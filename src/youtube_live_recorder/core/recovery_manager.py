import logging
from dataclasses import replace
from pathlib import Path

from youtube_live_recorder.data.models import ACTIVE_SESSIONS, TERMINAL_BROADCASTS, RecordingMode
from youtube_live_recorder.data.models import BroadcastStatus as B
from youtube_live_recorder.data.models import SessionStatus as S
from youtube_live_recorder.data.replays import ReplayStore
from youtube_live_recorder.utils.errors import AppError
from youtube_live_recorder.utils.filenames import recording_name
from youtube_live_recorder.utils.time import from_iso, to_iso, utc_now

LOGGER = logging.getLogger(__name__)
MEDIA_SUFFIXES = {".mp4", ".mkv", ".m4a", ".webm", ".ts", ".part"}


class RecoveryManager:
    def __init__(self, repository, settings, finalizer):
        self.repository, self.settings, self.finalizer = repository, settings, finalizer
        self.replays = ReplayStore(repository)

    def run(self, stop=None) -> None:
        # 호출자는 엔진 인스턴스 잠금을 가진다. 살아 있는 다른 녹화를 복구 대상으로 삼지 않는다.
        for session in self.repository.list_sessions():
            if stop is not None and stop.is_set():
                break
            active = session.status in ACTIVE_SESSIONS
            if not active and session.status != S.FAILED:
                continue
            item = self.repository.get_broadcast(session.broadcast_id)
            if item.status in TERMINAL_BROADCASTS:
                continue
            self.repository.mark_recovery_attempt(session.id)
            if active:
                if item.status not in {B.INTERRUPTED, B.RECOVERING}:
                    self.repository.transition(item.id, B.INTERRUPTED)
                if item.status != B.RECOVERING:
                    self.repository.transition(item.id, B.RECOVERING)
            saved = []
            for segment in self.repository.list_segments(session.id):
                try:
                    final_path = segment["final_path"]
                    if final_path:
                        inspection = self.finalizer.verifier.inspect(Path(final_path))
                        if inspection.valid:
                            saved.append(inspection)
                            continue
                    source = Path(segment["temporary_path"])
                    sources = tuple(
                        p
                        for p in source.iterdir()
                        if p.is_file() and p.suffix.lower() in MEDIA_SUFFIXES
                    )
                    # 저장 폴더 설정이 바뀌었어도 기존 조각은 원래 드라이브에서 복구한다.
                    root = Path(session.work_directory) if session.work_directory else source
                    folder = (
                        root.parent.parent
                        if root.parent.name == ".ylr-work"
                        else self.settings.save_folder
                    )
                    name = recording_name(
                        item.title or "방송",
                        from_iso(item.actual_start_at or session.started_at),
                        item.custom_filename,
                        replay=session.mode == RecordingMode.REPLAY,
                    )
                    name = f"{Path(name).stem}_복구{segment['segment_index'] + 1:02d}.mp4"
                    inspection = self.finalizer.finalize(sources, folder, name)
                    saved.append(inspection)
                    self.repository.finish_segment(segment["id"], inspection)
                except (OSError, AppError) as error:
                    self.repository.finish_segment(segment["id"], None, str(error))
                    LOGGER.warning("중단 파일 복구 실패 · 원본 보존")
            target = (
                B.ERROR_RETRYABLE
                if active and session.mode == RecordingMode.LIVE
                else B.REPLAY_WAIT
                if active
                else item.status
            )
            reason = (
                "중단된 작업을 검사했습니다. 구간 누락이 있을 수 있으며 원본 조각은 보존됩니다."
            )
            if session.status == S.CREATED:
                self.repository.finish_session(session.id, S.FAILED, target, reason=reason)
            elif saved:
                if session.status in {S.RUNNING, S.RECONNECTING}:
                    self.repository.set_session_state(session.id, S.FINALIZING)
                inspection = replace(
                    saved[0],
                    duration_seconds=sum(p.duration_seconds for p in saved),
                    size_bytes=sum(p.size_bytes for p in saved),
                )
                self.repository.finish_session(session.id, S.PARTIAL, target, inspection, reason)
            elif active:
                self.repository.finish_session(session.id, S.FAILED, target, reason=reason)
            self.replays.ensure(item.id, reason)
            if session.mode == RecordingMode.REPLAY:
                self.replays.defer(item.id, utc_now(), immediate=True)
            if active:
                self.repository.set_next_check(item.id, to_iso(utc_now()))
            self.repository.add_event(
                "recovery", reason, broadcast_id=item.id, session_id=session.id
            )
