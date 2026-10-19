import os
import subprocess
import sys
import time
from threading import Event, Timer

import pytest

from youtube_live_recorder.services.process_runner import ProcessRunner
from youtube_live_recorder.services.toolchain import Toolchain


@pytest.mark.parametrize("failure", [OSError("신호 실패"), subprocess.TimeoutExpired("signal", 5)])
def test_signal_helper_failure_still_returns_forced_stop(monkeypatch, failure):
    def interrupt(pid):
        raise failure

    monkeypatch.setattr(
        "youtube_live_recorder.services.process_runner.interrupt_process", interrupt
    )
    stop = Event()
    started = time.monotonic()
    result = ProcessRunner().run(
        [sys.executable, "-c", "import time; print('ready', flush=True); time.sleep(30)"],
        stop=stop,
        grace_seconds=0.1,
        on_line=lambda name, line: stop.set() if "ready" in line else None,
    )
    assert result.stopped and result.forced
    # Windows KILL_ON_JOB_CLOSE는 0을 종료 코드로 보고할 수 있다. forced가 판정 기준이다.
    assert time.monotonic() - started < 5
    assert "ready" in result.stdout


def test_separate_streams_and_nonzero_exit():
    result = ProcessRunner().run(
        [
            sys.executable,
            "-c",
            "import sys; print('표준 출력'); print('표준 오류', file=sys.stderr); sys.exit(7)",
        ]
    )
    assert result.return_code == 7
    assert "표준 출력" in result.stdout and "표준 오류" in result.stderr


def test_large_output_does_not_deadlock_and_is_bounded():
    result = ProcessRunner().run(
        [sys.executable, "-c", "print(('a'*1000+'\\n')*2000)"], output_limit=2048
    )
    assert result.return_code == 0
    assert len(result.stdout) <= 2048


@pytest.mark.skipif(os.name != "nt", reason="Windows 콘솔 신호 검증")
def test_hidden_console_ctrl_c_reaches_child():
    stop = Event()
    timer = Timer(1.5, stop.set)
    timer.start()
    try:
        result = ProcessRunner().run(
            [
                sys.executable,
                "-c",
                "import time\ntry:\n time.sleep(30)\n"
                "except KeyboardInterrupt:\n print('정상 중지')",
            ],
            stop=stop,
            grace_seconds=5,
        )
    finally:
        timer.cancel()
    assert result.stopped and not result.forced
    assert "정상 중지" in result.stdout


@pytest.mark.media
def test_ffmpeg_graceful_stop_finalizes_container(tmp_path):
    tools = Toolchain.discover()
    output = tmp_path / "한글 중지.mkv"
    stop = Event()
    timer = Timer(2.5, stop.set)
    timer.start()
    try:
        result = ProcessRunner().run(
            [
                str(tools.ffmpeg),
                "-hide_banner",
                "-loglevel",
                "warning",
                "-re",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=160x90:rate=10",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=44100",
                "-c:v",
                "mpeg4",
                "-c:a",
                "aac",
                "-t",
                "30",
                str(output),
            ],
            stop=stop,
            grace_seconds=10,
        )
    finally:
        timer.cancel()
    assert result.stopped and not result.forced, result.stderr
    assert output.stat().st_size > 0
    probe = ProcessRunner().run(
        [
            str(tools.ffprobe),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(output),
        ]
    )
    assert probe.return_code == 0
    assert 0 < float(probe.stdout) < 30
