"""데이터를 보내지 않는 로컬 HTTP 서버로 실제 yt-dlp → FFmpeg 시간 제한 검증."""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

import pytest

from youtube_live_recorder.data.models import Quality
from youtube_live_recorder.services.interfaces import CaptureRequest
from youtube_live_recorder.services.process_runner import ProcessRunner
from youtube_live_recorder.services.toolchain import Toolchain
from youtube_live_recorder.services.ytdlp_adapter import YtdlpAdapter


@pytest.mark.media
def test_ffmpeg_network_stall_returns_to_manager_without_forced_kill(tmp_path):
    release = Event()
    contacted = Event()

    class StalledHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "video/mp2t")
            self.send_header("Content-Length", "1000000")
            self.end_headers()
            self.wfile.flush()
            contacted.set()
            release.wait(40)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), StalledHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/stalled.ts"
    info = tmp_path / "stream.json"
    info.write_text(
        json.dumps(
            {
                "id": "local-stall",
                "title": "로컬 연결 정지 시험",
                "url": url,
                "webpage_url": url,
                "extractor": "generic",
                "extractor_key": "Generic",
                "ext": "ts",
                "protocol": "http",
                "height": 90,
                "vcodec": "mpeg4",
                "acodec": "aac",
            }
        ),
        encoding="utf-8",
    )
    adapter = YtdlpAdapter(Toolchain.discover())
    # 미리 조회한 로컬 정보만 사용한다. YouTube와 외부 인터넷에는 접속하지 않는다.
    args = adapter.capture_args(
        CaptureRequest("https://youtu.be/Abc_123-xYz", Quality.P720, tmp_path, False)
    )[:-2]
    started = time.monotonic()
    try:
        result = ProcessRunner().run(
            [*args, "--downloader", "ffmpeg", "--load-info-json", str(info)],
            kind="ytdlp",
            timeout=35,
        )
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert contacted.is_set(), result.stderr
    assert result.return_code != 0 and not result.timed_out and not result.forced, result.stderr
    # --print의 quiet 모드에서는 FFmpeg 오류 문구 대신 종료 코드만 출력한다.
    assert 14 <= time.monotonic() - started < 30
