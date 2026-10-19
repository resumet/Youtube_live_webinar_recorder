import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from youtube_live_recorder.services.windows_job import WindowsJob


@dataclass(frozen=True)
class ProcessResult:
    return_code: int
    stdout: str
    stderr: str
    stopped: bool = False
    timed_out: bool = False
    forced: bool = False


def worker_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).with_name("YouTubeLiveRecorderWorker.exe")), "--worker"]
    return [sys.executable, "-m", "youtube_live_recorder.services.worker"]


def interrupt_process(pid: int) -> int:
    if os.name != "nt":
        os.killpg(pid, signal.SIGINT)
        return 0
    helper = [str(Path(sys.executable).with_name("YouTubeLiveRecorderWorker.exe"))]
    if not getattr(sys, "frozen", False):
        helper = [sys.executable]
        helper += ["-m", "youtube_live_recorder"]
    helper += ["--signal-console", str(pid)]
    result = subprocess.run(
        helper,
        timeout=5,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdin=subprocess.DEVNULL,
        capture_output=True,
    )
    return result.returncode


class ProcessRunner:
    def run(
        self,
        args: list[str],
        *,
        kind: str = "command",
        cwd: Path | None = None,
        stop: threading.Event | None = None,
        timeout: float | None = 60,
        grace_seconds: float = 20,
        on_line: Callable[[str, str], None] | None = None,
        on_tick: Callable[[], None] | None = None,
        output_limit: int = 16 * 1024 * 1024,
    ) -> ProcessResult:
        """셸 없이 실행한다. 출력은 별도 reader가 소비하고 메모리 상한을 적용한다."""
        if stop is not None and stop.is_set():
            return ProcessResult(130, "", "", stopped=True)
        job = WindowsJob()
        options = {}
        if os.name == "nt":
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = subprocess.SW_HIDE
            options = {"creationflags": subprocess.CREATE_NEW_CONSOLE, "startupinfo": startup}
        else:
            options = {"start_new_session": True}
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        process = None
        readers = []
        outputs = {"stdout": deque(), "stderr": deque()}
        sizes = {"stdout": 0, "stderr": 0}
        started = time.monotonic()
        stop_started = None
        timed_out = forced = stopped = False

        def read_stream(stream, name):
            try:
                while chunk := stream.readline(65536):
                    line = chunk.decode("utf-8", errors="replace")
                    outputs[name].append(line)
                    sizes[name] += len(line)
                    while sizes[name] > output_limit and len(outputs[name]) > 1:
                        sizes[name] -= len(outputs[name].popleft())
                    if on_line:
                        try:
                            on_line(name, line)
                        except Exception:
                            logging.getLogger(__name__).exception("녹화 진행 정보 갱신 실패")
            finally:
                stream.close()

        try:
            process = subprocess.Popen(
                worker_command(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=env,
                **options,
            )
            if os.name == "nt":
                job.assign(int(process._handle))
            for name in outputs:
                reader = threading.Thread(
                    target=read_stream, args=(getattr(process, name), name), daemon=True
                )
                reader.start()
                readers.append(reader)
            # 시작 게이트: 자식 yt-dlp/FFmpeg 실행 전에 반드시 job에 연결한다.
            process.stdin.write(json.dumps({"kind": kind, "args": args}).encode("utf-8") + b"\n")
            process.stdin.close()
            while process.poll() is None:
                now = time.monotonic()
                if stop_started is None:
                    timed_out = timeout is not None and now - started >= timeout
                    stopped = stop is not None and stop.is_set()
                    if stopped or timed_out:
                        stop_started = now
                        try:
                            if interrupt_process(process.pid):
                                logging.getLogger(__name__).warning(
                                    "정상 중지 신호를 전달하지 못했습니다. 유예 후 종료합니다."
                                )
                        except (OSError, subprocess.TimeoutExpired):
                            # 신호 도우미가 실패해도 아래의 제한 시간과 Job 정리를 유지한다.
                            # 예외로 탈출하면 녹화기가 이미 받은 파일을 마무리할 수 없다.
                            logging.getLogger(__name__).warning(
                                "정상 중지 신호 처리 실패. 유예 후 종료합니다."
                            )
                    elif on_tick:
                        on_tick()
                elif now - stop_started >= grace_seconds:
                    forced = True
                    if os.name == "nt":
                        job.close()
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
                    break
                time.sleep(0.05)
            process.wait(timeout=10)
        finally:
            job.close()
            if process and process.poll() is None:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait(timeout=10)
            for reader in readers:
                reader.join(timeout=10)
        return ProcessResult(
            process.returncode,
            "".join(outputs["stdout"]),
            "".join(outputs["stderr"]),
            stopped,
            timed_out,
            forced,
        )
