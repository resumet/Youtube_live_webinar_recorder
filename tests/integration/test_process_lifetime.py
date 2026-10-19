import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from threading import Event, Timer

import pytest

from youtube_live_recorder.services.process_runner import ProcessRunner
from youtube_live_recorder.utils.instance_lock import InstanceLock

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows 프로세스 수명 검증")


def running(pid):
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = api.OpenProcess(0x100000, False, pid)
    if not handle:
        return False
    try:
        return api.WaitForSingleObject(handle, 0) == 0x102
    finally:
        api.CloseHandle(handle)


def test_forced_stop_kills_ctrl_c_ignoring_child(tmp_path):
    pid_file = tmp_path / "child.pid"
    code = (
        "import signal, time, os; from pathlib import Path; "
        "signal.signal(signal.SIGINT, signal.SIG_IGN); "
        f"Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(30)"
    )
    stop = Event()
    timer = Timer(1, stop.set)
    timer.start()
    try:
        result = ProcessRunner().run([sys.executable, "-c", code], stop=stop, grace_seconds=0.5)
    finally:
        timer.cancel()
    assert result.forced
    assert not running(int(pid_file.read_text()))


def test_parent_crash_kills_descendants(tmp_path):
    pid_file = tmp_path / "crash-child.pid"
    child = (
        "import os,time; from pathlib import Path; "
        f"Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(30)"
    )
    parent = (
        "from youtube_live_recorder.services.process_runner import ProcessRunner; "
        f"ProcessRunner().run({[sys.executable, '-c', child]!r}, timeout=40)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", parent], creationflags=subprocess.CREATE_NO_WINDOW
    )
    try:
        deadline = time.monotonic() + 10
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert pid_file.exists()
        child_pid = int(pid_file.read_text())
        assert running(child_pid)
        process.kill()
        process.wait(timeout=5)
        deadline = time.monotonic() + 5
        while running(child_pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not running(child_pid)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_application_lock_blocks_second_process_and_releases(tmp_path):
    path = tmp_path / "engine.lock"
    code = (
        "from youtube_live_recorder.utils.instance_lock import InstanceLock; "
        f"from pathlib import Path; InstanceLock(Path({str(path)!r})).acquire()"
    )
    with InstanceLock(path):
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert result.returncode != 0
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 0
