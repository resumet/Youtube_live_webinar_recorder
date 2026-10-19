"""Job Object 할당 전에는 stdin 시작 메시지를 기다리는 숨겨진 콘솔 워커."""

import json
import os
import subprocess
import sys


def main() -> int:
    if os.name == "nt":
        import ctypes

        ctypes.windll.kernel32.SetConsoleCtrlHandler(None, False)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    message = json.loads(sys.stdin.buffer.readline().decode("utf-8"))
    if message["kind"] == "ytdlp":
        import yt_dlp

        yt_dlp.main(message["args"])
        return 0
    child = subprocess.Popen(message["args"], stdin=subprocess.DEVNULL)
    while True:
        try:
            return child.wait()
        except KeyboardInterrupt:
            # CTRL_C는 동일 콘솔의 FFmpeg에도 도착한다. 컨테이너 마무리를 기다린다.
            continue


if __name__ == "__main__":
    raise SystemExit(main())
