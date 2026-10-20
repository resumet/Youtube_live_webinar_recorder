"""번들에서도 실행하는 오프라인 미디어 검증. YouTube 서비스 시험과 구분한다."""

import functools
import importlib.resources
import json
import threading
from datetime import timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
from uuid import uuid4

from youtube_live_recorder.config import Settings
from youtube_live_recorder.core.archive_downloads import ArchiveDownloads
from youtube_live_recorder.core.recording_manager import RecordingManager
from youtube_live_recorder.core.scheduler import Scheduler
from youtube_live_recorder.data.db import Database
from youtube_live_recorder.data.models import Quality, SessionStatus
from youtube_live_recorder.data.repository import Repository
from youtube_live_recorder.services.ffmpeg_adapter import FFmpegAdapter
from youtube_live_recorder.services.ffprobe_adapter import FFprobeAdapter
from youtube_live_recorder.services.interfaces import BroadcastMetadata, LiveState
from youtube_live_recorder.services.process_runner import ProcessRunner
from youtube_live_recorder.services.toolchain import Toolchain
from youtube_live_recorder.services.ytdlp_adapter import YtdlpAdapter
from youtube_live_recorder.utils.time import utc_now


def run_self_test(root: Path) -> dict:
    folder = root / "self-test" / str(uuid4())
    folder.mkdir(parents=True)
    tools = Toolchain.discover()
    runner = ProcessRunner()
    ytdlp = runner.run(["--ignore-config", "--version"], kind="ytdlp", timeout=30)
    if ytdlp.return_code:
        raise RuntimeError("번들 yt-dlp 실행에 실패했습니다.")
    javascript = runner.run([str(tools.javascript), "eval", "console.log(1+1)"], timeout=30)
    if javascript.return_code or javascript.stdout.strip() != "2":
        raise RuntimeError("번들 JavaScript 런타임 실행에 실패했습니다.")
    ejs = importlib.resources.files("yt_dlp_ejs").joinpath("yt", "solver", "lib.min.js")
    if not ejs.is_file():
        raise RuntimeError("번들 EJS 파일이 없습니다.")
    stop = threading.Event()

    def progress(name, line):
        if name == "stdout" and line.startswith("out_time_us="):
            try:
                if int(line.split("=", 1)[1]) >= 1_000_000:
                    stop.set()
            except ValueError:
                pass

    raw = folder / "fixture.ts"
    result = runner.run(
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
            "30",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-progress",
            "pipe:1",
            "-f",
            "mpegts",
            str(raw),
        ],
        stop=stop,
        on_line=progress,
        timeout=40,
    )
    if not result.stopped or result.forced:
        raise RuntimeError("번들 녹화 도구의 정상 중지 검증에 실패했습니다.")
    finalizer = FFmpegAdapter(tools.ffmpeg, FFprobeAdapter(tools.ffprobe))
    sample = finalizer.finalize((raw,), folder, "정상_중지_검증.mp4")

    concurrent_clients = set()
    clients_lock = threading.Lock()
    all_clients = threading.Event()

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            identifier = parse_qs(urlparse(self.path).query).get("stream", [""])[0]
            with clients_lock:
                concurrent_clients.add(identifier)
                if len(concurrent_clients) == 5:
                    all_clients.set()
            if not all_clients.wait(60):
                self.send_error(503)
                return
            super().do_GET()

    class Metadata:
        def __init__(self):
            self.calls = {}
            self.lock = threading.Lock()

        def fetch(self, url):
            identifier = url[-11:]
            with self.lock:
                count = self.calls.get(identifier, 0) + 1
                self.calls[identifier] = count
            return BroadcastMetadata(
                identifier,
                "자체 생성 시험 영상",
                "로컬",
                "",
                LiveState.LIVE if count == 1 else LiveState.WAS_LIVE,
            )

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(folder))
    )
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    database = Database(folder / "test.db")
    database.initialize()
    repository = Repository(database)
    metadata, adapter = Metadata(), YtdlpAdapter(tools)
    original_args = adapter.capture_args
    capture_requests = []

    def local_args(request):
        capture_requests.append(request)
        args = original_args(request)
        # 진단 전용 로컬 서버. 실제 등록 URL의 제한/인증 처리에는 관여하지 않는다.
        args[-1] = (
            f"http://127.0.0.1:{server.server_port}/{quote(sample.path.name)}"
            f"?stream={request.url[-11:]}"
        )
        return args

    adapter.capture_args = local_args
    manager = RecordingManager(
        repository,
        Settings(folder, min_free_bytes=0),
        metadata,
        adapter,
        finalizer,
        confirmation_seconds=0.1,
    )
    try:
        for index in range(5):
            repository.add_broadcast(
                f"https://youtu.be/Test{index:07}", permission_confirmed=True, quality=Quality.BEST
            )
        Scheduler(repository, metadata, manager).tick(utc_now() + timedelta(seconds=1))
        for task in manager.tasks.values():
            task.future.result(timeout=120)
        sessions = repository.list_sessions()
        if (
            len(sessions) != 5
            or not all_clients.is_set()
            or any(s.status != SessionStatus.COMPLETE or not s.ffprobe_ok for s in sessions)
            or len({s.output_path for s in sessions}) != 5
        ):
            raise RuntimeError("번들 미디어 파이프라인 또는 기록 검증에 실패했습니다.")
        archive = ArchiveDownloads(repository, metadata).register(
            "https://youtube.com/live/Test0000000?t=60",
            permission_confirmed=True,
            quality=Quality.BEST,
        )
        Scheduler(repository, metadata, manager).tick(utc_now() + timedelta(seconds=1))
        manager.future.result(timeout=120)
        downloaded = next(s for s in repository.list_sessions() if s.broadcast_id == archive.id)
        if (
            downloaded.status != SessionStatus.COMPLETE
            or not downloaded.ffprobe_ok
            or downloaded.mode != "REPLAY"
            or capture_requests[-1].from_start
            or abs(downloaded.duration_seconds - sample.duration_seconds) > 0.1
        ):
            raise RuntimeError("종료영상 전체 다운로드 또는 길이 검사에 실패했습니다.")
        report = {
            "성공": True,
            "yt-dlp": ytdlp.stdout.strip(),
            "JavaScript": "실행 확인",
            "정상 중지": True,
            "MP4 검사": True,
            "DB 검사": database.check_integrity(),
            "검증 파일": sessions[0].output_path,
            "동시 녹화 수": len(concurrent_clients),
            "전체 파일": [s.output_path for s in sessions],
            "종료영상 전체 다운로드": True,
            "종료영상 파일": downloaded.output_path,
            "종료영상 길이": downloaded.duration_seconds,
            "원본 길이": sample.duration_seconds,
            "범위": "로컬 영상 5개 동시 전송 + 종료영상 전체 다운로드 · 실제 YouTube 시험 아님",
        }
        (folder / "result.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return report
    finally:
        manager.shutdown()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
