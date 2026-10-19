import functools
import os
import subprocess
import sys
import threading
import time
from datetime import timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from youtube_live_recorder.config import Settings
from youtube_live_recorder.core.recording_manager import RecordingManager
from youtube_live_recorder.core.recovery_manager import RecoveryManager
from youtube_live_recorder.core.scheduler import Scheduler
from youtube_live_recorder.data.db import Database
from youtube_live_recorder.data.models import BroadcastStatus, Quality, SessionStatus
from youtube_live_recorder.data.repository import Repository
from youtube_live_recorder.services.ffmpeg_adapter import FFmpegAdapter
from youtube_live_recorder.services.ffprobe_adapter import FFprobeAdapter
from youtube_live_recorder.services.interfaces import BroadcastMetadata, CaptureRequest, LiveState
from youtube_live_recorder.services.process_runner import ProcessRunner
from youtube_live_recorder.services.toolchain import Toolchain
from youtube_live_recorder.services.ytdlp_adapter import YtdlpAdapter
from youtube_live_recorder.utils.time import utc_now


def test_crashed_process_reopens_database_and_recovers_real_media(sample, tmp_path, tools):
    database_path = tmp_path / "crashed.db"
    ready = tmp_path / "ready"
    script = tmp_path / "crash_fixture.py"
    script.write_text(
        """
import sys, shutil, time
from pathlib import Path
from youtube_live_recorder.data.db import Database
from youtube_live_recorder.data.repository import Repository
from youtube_live_recorder.data.models import BroadcastStatus as B
from youtube_live_recorder.data.models import SessionStatus as S, RecordingMode
db = Database(Path(sys.argv[1]))
db.initialize()
repo = Repository(db)
item = repo.add_broadcast("https://youtu.be/Abc_123-xYz", permission_confirmed=True)
repo.transition(item.id, B.LIVE_DETECTED)
session = repo.claim_session(item.id, RecordingMode.LIVE)
work = Path(sys.argv[2]).parent / ".ylr-work" / session.id
work.mkdir(parents=True)
repo.set_session_state(session.id, S.RUNNING, work_directory=str(work))
repo.add_segment(session.id, 0, str(work))
shutil.copyfile(sys.argv[2], work / "capture.mp4.part")
Path(sys.argv[3]).write_text(session.id)
time.sleep(30)
""",
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [sys.executable, str(script), str(database_path), str(sample), str(ready)],
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists()
        session_id = ready.read_text()
        process.kill()
        process.wait(5)
        database = Database(database_path)
        database.initialize()
        repo = Repository(database)
        finalizer = FFmpegAdapter(tools.ffmpeg, FFprobeAdapter(tools.ffprobe))
        recovery = RecoveryManager(repo, Settings(tmp_path), finalizer)
        recovery.run()
        session = repo.get_session(session_id)
        assert session.status == SessionStatus.PARTIAL and session.ffprobe_ok
        assert finalizer.verifier.inspect(Path(session.output_path)).valid
        assert repo.get_broadcast(session.broadcast_id).status == BroadcastStatus.ERROR_RETRYABLE
        assert repo.active_session() is None and database.check_integrity()
        assert list((tmp_path / ".ylr-work").rglob("*.part"))
        assert len(list(tmp_path.glob("*복구*.mp4"))) == 1
        recovery.run()
        assert len(list(tmp_path.glob("*복구*.mp4"))) == 1
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(5)


pytestmark = pytest.mark.media


@pytest.fixture
def tools():
    return Toolchain.discover()


@pytest.fixture
def sample(tmp_path, tools):
    path = tmp_path / "original.mp4"
    result = ProcessRunner().run(
        [
            str(tools.ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440",
            "-t",
            "1",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            str(path),
        ]
    )
    assert result.return_code == 0, result.stderr
    return path


def test_real_ffprobe_and_remux_preserve_originals(sample, tmp_path, tools):
    probe = FFprobeAdapter(tools.ffprobe)
    finalizer = FFmpegAdapter(tools.ffmpeg, probe)
    result = finalizer.finalize((sample,), tmp_path, "한글 파일.mp4")
    assert result.valid and result.audio_codec == "aac"
    assert result.video_codec == "mpeg4" and result.height == 90
    assert sample.exists() and result.path.exists()
    again = finalizer.finalize((sample,), tmp_path, "한글 파일.mp4")
    assert again.path.name == "한글 파일 (2).mp4"
    assert result.path.exists()


def test_audio_missing_and_corrupt_media_rejected(tmp_path, tools):
    video = tmp_path / "silent.mp4"
    ProcessRunner().run(
        [
            str(tools.ffmpeg),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=10",
            "-t",
            "0.5",
            "-c:v",
            "mpeg4",
            str(video),
        ]
    )
    probe = FFprobeAdapter(tools.ffprobe)
    assert not probe.inspect(video).valid
    corrupt = tmp_path / "broken.mp4"
    corrupt.write_bytes(b"not a media file")
    assert not probe.inspect(corrupt).valid


def test_ytdlp_local_http_download_and_mp4_pipeline(sample, tmp_path, tools, monkeypatch):
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(tmp_path))
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    adapter = YtdlpAdapter(tools)
    original_args = adapter.capture_args

    def local_args(request):
        args = original_args(request)
        # YouTube 사이트 추출은 별도 실서비스 시험. 여기서는 동일 downloader/프로세스 경로 검증.
        args[-1] = f"http://127.0.0.1:{server.server_port}/{sample.name}"
        return args

    monkeypatch.setattr(adapter, "capture_args", local_args)
    try:
        result = adapter.capture(
            CaptureRequest("https://youtu.be/Abc_123-xYz", Quality.BEST, tmp_path / "work", False),
            threading.Event(),
        )
        assert result.return_code == 0 and result.files
        finalized = FFmpegAdapter(tools.ffmpeg, FFprobeAdapter(tools.ffprobe)).finalize(
            result.files, tmp_path, "로컬 다운로드.mp4"
        )
        assert finalized.valid and finalized.duration_seconds >= 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_scheduler_to_real_download_to_verified_database_history(
    sample,
    tmp_path,
    tools,
    monkeypatch,
    repository,
):
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

    class Metadata:
        def __init__(self):
            self.calls = 0

        def fetch(self, url):
            self.calls += 1
            return BroadcastMetadata(
                "Abc_123-xYz",
                "엔진 통합 방송",
                "로컬 채널",
                "",
                LiveState.LIVE if self.calls == 1 else LiveState.WAS_LIVE,
            )

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(tmp_path))
    )
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    adapter = YtdlpAdapter(tools)
    original_args = adapter.capture_args

    def local_args(request):
        args = original_args(request)
        args[-1] = f"http://127.0.0.1:{server.server_port}/{sample.name}"
        return args

    monkeypatch.setattr(adapter, "capture_args", local_args)
    metadata = Metadata()
    manager = RecordingManager(
        repository,
        Settings(tmp_path, min_free_bytes=0),
        metadata,
        adapter,
        FFmpegAdapter(tools.ffmpeg, FFprobeAdapter(tools.ffprobe)),
    )
    item = repository.add_broadcast(
        "https://youtu.be/Abc_123-xYz", permission_confirmed=True, quality=Quality.BEST
    )
    try:
        Scheduler(repository, metadata, manager).tick(utc_now() + timedelta(seconds=1))
        manager.future.result(timeout=30)
        session = repository.list_sessions()[0]
        assert repository.get_broadcast(item.id).status == BroadcastStatus.COMPLETED
        assert session.status == SessionStatus.COMPLETE and session.ffprobe_ok
        assert session.size_bytes > 0 and session.duration_seconds > 0
        assert repository.active_session() is None
        assert sample.exists()
    finally:
        manager.shutdown()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
