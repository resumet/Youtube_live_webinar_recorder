"""자체 생성 스트림으로 GUI와 녹화 엔진을 실시간 장시간 실행하는 개발 검증."""

import ctypes
import json
import os
import time
from dataclasses import replace
from pathlib import Path
from threading import Event

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from youtube_live_recorder.config import Settings
from youtube_live_recorder.core.engine import Engine
from youtube_live_recorder.data.models import SessionStatus
from youtube_live_recorder.services.interfaces import BroadcastMetadata, CaptureResult, LiveState
from youtube_live_recorder.services.process_runner import ProcessRunner
from youtube_live_recorder.services.toolchain import Toolchain
from youtube_live_recorder.ui.controller import Controller
from youtube_live_recorder.ui.main_window import MainWindow


def resident_bytes() -> int:
    if os.name != "nt":
        return 0

    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
            (name, ctypes.c_size_t)
            for name in (
                "peak",
                "working",
                "peak_page",
                "page",
                "peak_nonpage",
                "nonpage",
                "pagefile",
                "peak_pagefile",
            )
        ]

    value = Counters()
    value.cb = ctypes.sizeof(value)
    api = ctypes.WinDLL("kernel32")
    api.GetCurrentProcess.restype = ctypes.c_void_p
    psapi = ctypes.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    if not psapi.GetProcessMemoryInfo(api.GetCurrentProcess(), ctypes.byref(value), value.cb):
        return 0
    return value.working


def run_soak(context, seconds: int, report: Path) -> int:
    if seconds < 5 or seconds > 24 * 60 * 60:
        raise RuntimeError("장시간 검증 시간은 5초~24시간이어야 합니다.")
    if context.repository.list_broadcasts(include_terminal=True):
        raise RuntimeError("장시간 검증에는 방송이 등록되지 않은 별도 데이터 폴더가 필요합니다.")
    folder = context.paths.root / "soak-recordings"
    context.repository.set_setting("save_folder", str(folder))
    context = replace(context, settings=Settings.load(context.repository))
    ended = Event()
    tools = Toolchain.discover()

    class Metadata:
        def fetch(self, url):
            return BroadcastMetadata(
                "Abc_123-xYz",
                "장시간 자체 생성 시험",
                "로컬",
                "",
                LiveState.WAS_LIVE if ended.is_set() else LiveState.LIVE,
            )

    class Capture:
        def capture(self, request, stop):
            request.work_directory.mkdir(parents=True)
            path = request.work_directory / "capture.ts"
            if request.on_quality:
                request.on_quality(90)
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
                    "testsrc2=size=160x90:rate=2",
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=r=16000:cl=mono",
                    "-t",
                    str(seconds),
                    "-c:v",
                    "mpeg4",
                    "-q:v",
                    "20",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "16k",
                    "-f",
                    "mpegts",
                    str(path),
                ],
                stop=stop,
                timeout=seconds + 90,
            )
            ended.set()
            return CaptureResult(
                result.return_code,
                (path,),
                result.stopped,
                request.from_start,
                forced=result.forced,
            )

    def engine_factory(ctx):
        engine = Engine(ctx)
        provider = Metadata()
        engine.recordings.metadata = provider
        engine.recordings.backend = Capture()
        engine.scheduler.metadata = provider
        engine.scheduler.replays.metadata = provider
        return engine

    context.repository.add_broadcast("https://youtu.be/Abc_123-xYz", permission_confirmed=True)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    controller = Controller(context, engine_factory=engine_factory)
    window = MainWindow(controller)
    window.show()
    started = time.monotonic()
    state = {
        "시작 프로세스": os.getpid(),
        "요청 시간(초)": seconds,
        "UI 응답 횟수": 0,
        "최대 UI 간격(초)": 0.0,
        "최대 메모리(바이트)": 0,
        "성공": False,
        "범위": "실시간 자체 생성 영상 · 실제 YouTube 방송 아님",
    }
    previous = started
    samples = []
    report.parent.mkdir(parents=True, exist_ok=True)
    finishing = False

    def save():
        temporary = report.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({**state, "메모리 표본": samples}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, report)

    def heartbeat():
        nonlocal previous, finishing
        now = time.monotonic()
        state["UI 응답 횟수"] += 1
        state["최대 UI 간격(초)"] = max(state["최대 UI 간격(초)"], now - previous)
        state["경과 시간(초)"] = now - started
        previous = now
        if not samples or now - started - samples[-1][0] >= 60:
            memory = resident_bytes()
            state["최대 메모리(바이트)"] = max(state["최대 메모리(바이트)"], memory)
            samples.append((now - started, memory))
            save()
        sessions = window.snapshot.sessions if window.snapshot else ()
        terminal = next(
            (
                s
                for s in sessions
                if s.status in {SessionStatus.COMPLETE, SessionStatus.PARTIAL, SessionStatus.FAILED}
            ),
            None,
        )
        if not finishing and (terminal or now - started > seconds + 120):
            finishing = True
            state["성공"] = bool(
                terminal
                and terminal.status == SessionStatus.COMPLETE
                and terminal.ffprobe_ok
                and now - started >= seconds
                and state["최대 UI 간격(초)"] < 5
            )
            if terminal:
                state["파일"] = terminal.output_path
                state["파일 길이(초)"] = terminal.duration_seconds
                state["파일 크기(바이트)"] = terminal.size_bytes
                state["상태"] = terminal.status
            save()
            window.quitting = True
            window.timer.stop()
            controller.close_async()

    timer = QTimer(window)
    timer.timeout.connect(heartbeat)
    timer.start(100)
    app.exec()
    state["정상 종료"] = True
    save()
    return 0 if state["성공"] else 1
