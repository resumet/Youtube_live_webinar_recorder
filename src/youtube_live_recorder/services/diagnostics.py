"""번들에서도 실행하는 오프라인 미디어 검증. YouTube 서비스 시험과 구분한다."""

import functools
import importlib.resources
import json
import threading
from datetime import timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

from youtube_live_recorder.config import Settings
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

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

    class Metadata:
        calls = 0

        def fetch(self, url):
            self.calls += 1
            return BroadcastMetadata(
                "Abc_123-xYz",
                "자체 생성 시험 영상",
                "로컬",
                "",
                LiveState.LIVE if self.calls == 1 else LiveState.WAS_LIVE,
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

    def local_args(request):
        args = original_args(request)
        # 진단 전용 로컬 서버. 실제 등록 URL의 제한/인증 처리에는 관여하지 않는다.
        from urllib.parse import quote

        args[-1] = f"http://127.0.0.1:{server.server_port}/{quote(sample.path.name)}"
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
        repository.add_broadcast(
            "https://youtu.be/Abc_123-xYz", permission_confirmed=True, quality=Quality.BEST
        )
        Scheduler(repository, metadata, manager).tick(utc_now() + timedelta(seconds=1))
        manager.future.result(timeout=120)
        session = repository.list_sessions()[0]
        if session.status != SessionStatus.COMPLETE or not session.ffprobe_ok:
            raise RuntimeError("번들 미디어 파이프라인 또는 기록 검증에 실패했습니다.")
        report = {
            "성공": True,
            "yt-dlp": ytdlp.stdout.strip(),
            "JavaScript": "실행 확인",
            "정상 중지": True,
            "MP4 검사": True,
            "DB 검사": database.check_integrity(),
            "검증 파일": session.output_path,
            "범위": "로컬 영상 · 실제 YouTube 시험 아님",
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
