import functools
import json
import os
import subprocess
import sys
import threading
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from youtube_live_recorder.config import Settings
from youtube_live_recorder.core.archive_downloads import ArchiveDownloads
from youtube_live_recorder.core.recording_manager import RecordingManager
from youtube_live_recorder.core.recovery_manager import RecoveryManager
from youtube_live_recorder.core.scheduler import Scheduler
from youtube_live_recorder.data.db import Database
from youtube_live_recorder.data.models import BroadcastStatus, Quality, SessionStatus
from youtube_live_recorder.data.replays import ReplayStore
from youtube_live_recorder.data.repository import Repository
from youtube_live_recorder.services.ffmpeg_adapter import FFmpegAdapter
from youtube_live_recorder.services.ffprobe_adapter import FFprobeAdapter
from youtube_live_recorder.services.interfaces import (
    BroadcastMetadata,
    CaptureRequest,
    CaptureResult,
    LiveState,
)
from youtube_live_recorder.services.process_runner import ProcessRunner
from youtube_live_recorder.services.toolchain import Toolchain
from youtube_live_recorder.services.ytdlp_adapter import YtdlpAdapter
from youtube_live_recorder.utils.errors import ErrorCode
from youtube_live_recorder.utils.time import utc_now


def test_stopping_one_real_capture_leaves_other_process_recording(repository, tmp_path, tools):
    ready = {f"Test{i:07}": threading.Event() for i in range(2)}
    results = {}

    class Streams:
        def fetch(self, url):
            return BroadcastMetadata(url[-11:], "동시 녹화", "로컬", "", LiveState.LIVE)

        def capture(self, request, stop):
            key = request.url[-11:]
            request.work_directory.mkdir(parents=True)
            source = request.work_directory / "capture.ts"

            def progress(channel, line):
                if channel == "stdout" and line.startswith("out_time_us="):
                    value = line.strip().split("=", 1)[1]
                    if value.isdigit() and int(value) >= 1_000_000:
                        ready[key].set()

            result = ProcessRunner().run(
                [
                    str(tools.ffmpeg),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-re",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=160x90:rate=5",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440",
                    "-t",
                    "60",
                    "-c:v",
                    "mpeg4",
                    "-c:a",
                    "aac",
                    "-progress",
                    "pipe:1",
                    "-f",
                    "mpegts",
                    str(source),
                ],
                stop=stop,
                on_line=progress,
                timeout=75,
            )
            results[key] = result
            return CaptureResult(result.return_code, (source,), result.stopped, request.from_start)

    streams = Streams()
    manager = RecordingManager(
        repository,
        Settings(tmp_path, min_free_bytes=0),
        streams,
        streams,
        FFmpegAdapter(tools.ffmpeg, FFprobeAdapter(tools.ffprobe)),
    )
    items = [
        repository.add_broadcast(f"https://youtu.be/Test{i:07}", permission_confirmed=True)
        for i in range(2)
    ]
    try:
        Scheduler(repository, streams, manager).tick(utc_now() + timedelta(seconds=1))
        assert all(event.wait(15) for event in ready.values())
        first, second = repository.active_sessions()
        manager.stop(expected_session_id=first.id)
        manager.tasks[first.id].future.result(20)
        assert not manager.tasks[second.id].future.done()
        assert repository.get_broadcast(second.broadcast_id).status == BroadcastStatus.RECORDING
        manager.stop(expected_session_id=second.id)
        manager.tasks[second.id].future.result(20)
        assert all(result.stopped and not result.forced for result in results.values())
        assert all(
            repository.get_broadcast(i.id).status == BroadcastStatus.CANCELLED for i in items
        )
        assert all(
            s.ffprobe_ok and s.status == SessionStatus.PARTIAL for s in repository.list_sessions()
        )
    finally:
        manager.shutdown()


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


@pytest.mark.parametrize("archive", [False, True])
def test_scheduler_to_real_download_to_verified_database_history(
    sample,
    tmp_path,
    tools,
    monkeypatch,
    repository,
    archive,
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
                LiveState.LIVE if self.calls == 1 and not archive else LiveState.WAS_LIVE,
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
        if archive:
            assert not request.from_start
            assert "--download-sections" not in args
            assert "--abort-on-unavailable-fragments" in args
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
    item = (
        ArchiveDownloads(repository, metadata).register(
            "https://youtube.com/live/Abc_123-xYz?t=60",
            permission_confirmed=True,
            quality=Quality.BEST,
        )
        if archive
        else repository.add_broadcast(
            "https://youtu.be/Abc_123-xYz", permission_confirmed=True, quality=Quality.BEST
        )
    )
    try:
        Scheduler(repository, metadata, manager).tick(utc_now() + timedelta(seconds=1))
        manager.future.result(timeout=30)
        session = repository.list_sessions()[0]
        assert repository.get_broadcast(item.id).status == BroadcastStatus.COMPLETED
        assert session.status == SessionStatus.COMPLETE and session.ffprobe_ok
        assert session.size_bytes > 0 and session.duration_seconds > 0
        original = manager.finalizer.verifier.inspect(sample)
        assert abs(session.duration_seconds - original.duration_seconds) < 0.1
        if archive:
            assert session.mode == "REPLAY" and not session.from_start_attempted
        assert repository.active_session() is None
        assert sample.exists()
    finally:
        manager.shutdown()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)


def test_real_interrupted_http_reconnect_keeps_partial_and_verified_recovered_file(
    sample, tmp_path, tools, monkeypatch, repository
):
    payload = sample.read_bytes()
    interrupted = threading.Event()
    interrupted.set()
    contacts = {"broken": 0, "recovered": 0}

    class InterruptedHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            broken = interrupted.is_set()
            contacts["broken" if broken else "recovered"] += 1
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                # 본문 길이를 채우기 전에 실제 연결을 닫는다. 다음 캡처부터 전체 본문을 보낸다.
                self.wfile.write(payload[: len(payload) // 3] if broken else payload)
                self.wfile.flush()
            except OSError:
                pass
            self.close_connection = True

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), InterruptedHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    info = tmp_path / "local-info.json"
    url = f"http://127.0.0.1:{server.server_port}/stream.mp4"
    info.write_text(
        json.dumps(
            {
                "id": "Abc_123-xYz",
                "title": "로컬 연결 복구 시험",
                "url": url,
                "webpage_url": url,
                "extractor": "generic",
                "extractor_key": "Generic",
                "ext": "mp4",
                "protocol": "http",
                "height": 90,
                "vcodec": "mpeg4",
                "acodec": "aac",
            }
        ),
        encoding="utf-8",
    )
    adapter = YtdlpAdapter(tools)
    original_args = adapter.capture_args
    original_capture = adapter.capture
    results = []

    def local_args(request):
        # 사이트 조회만 대체한다. 오류 판정·다운로더 재시도·프로세스 실행은 실제 구현을 쓴다.
        return [*original_args(request)[:-2], "--load-info-json", str(info)]

    def capture(request, stop):
        if results:
            interrupted.clear()
        result = original_capture(request, stop)
        results.append(result)
        return result

    monkeypatch.setattr(adapter, "capture_args", local_args)
    monkeypatch.setattr(adapter, "capture", capture)

    class Metadata:
        def fetch(self, _url):
            return BroadcastMetadata(
                "Abc_123-xYz",
                "연결 복구 시험",
                "로컬 채널",
                "",
                LiveState.WAS_LIVE if len(results) >= 2 else LiveState.LIVE,
            )

    delays = []
    finalizer = FFmpegAdapter(tools.ffmpeg, FFprobeAdapter(tools.ffprobe))
    manager = RecordingManager(
        repository,
        Settings(tmp_path / "recordings", min_free_bytes=0, max_reconnect_attempts=1),
        Metadata(),
        adapter,
        finalizer,
        retry_wait=lambda stop, delay: delays.append(delay) or False,
        jitter=lambda *_: 0,
        confirmation_seconds=0,
    )
    item = repository.add_broadcast("https://youtu.be/Abc_123-xYz", permission_confirmed=True)
    repository.transition(item.id, BroadcastStatus.LIVE_DETECTED)
    try:
        session = manager.start(item.id)
        manager.future.result(timeout=45)
        assert len(results) == 2
        assert results[0].return_code != 0
        assert results[0].error_code == ErrorCode.NETWORK_DISCONNECTED
        assert not results[0].forced and results[1].return_code == 0
        assert contacts["broken"] >= 4 and contacts["recovered"] >= 1
        assert delays == [15]
        assert results[0].files and all(path.is_file() for path in results[0].files)
        assert any(0 < path.stat().st_size < len(payload) for path in results[0].files)
        assert set(results[0].files).isdisjoint(results[1].files)
        saved = repository.get_session(session.id)
        assert saved.status == SessionStatus.PARTIAL and saved.ffprobe_ok
        assert finalizer.verifier.inspect(Path(saved.output_path)).valid
        assert repository.get_broadcast(item.id).status == BroadcastStatus.REPLAY_WAIT
        assert ReplayStore(repository).get(item.id)["deadline_at"]
        assert repository.active_session() is None and repository.database.check_integrity()
    finally:
        manager.shutdown()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
