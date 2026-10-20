"""Windows 설치/재설치/제거 검증. 기존 제품 설치나 실행 중 앱이 있으면 중단한다."""

import argparse
import ctypes
import hashlib
import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from verify_package import verify

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    r"\{35C68D30-7145-4C68-8A1E-37E7E726D209}_is1"
)


def installed_locations() -> list[Path]:
    import winreg

    found = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, REGISTRY_KEY, 0, winreg.KEY_READ | view) as key:
                    found.append(Path(winreg.QueryValueEx(key, "InstallLocation")[0]).resolve())
            except FileNotFoundError:
                continue
    return found


def application_running() -> bool:
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenMutexW.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_wchar_p]
    api.OpenMutexW.restype = ctypes.c_void_p
    api.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = api.OpenMutexW(0x100000, False, "Local\\YouTubeLiveRecorder.Running")
    if not handle:
        if ctypes.get_last_error() != 2:
            raise ctypes.WinError(ctypes.get_last_error())
        return False
    api.CloseHandle(handle)
    return True


def run(args: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess:
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW,
        startupinfo=startup,
    )


def database_state(path: Path) -> tuple:
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as connection:
        broadcasts = connection.execute(
            "SELECT video_id, status, custom_filename FROM broadcasts ORDER BY registered_at"
        ).fetchall()
        settings = connection.execute(
            "SELECT key, value_json FROM app_settings ORDER BY key"
        ).fetchall()
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    return broadcasts, settings


def verify_installer(setup: Path, *, guard_only: bool = False) -> Path:
    if os.name != "nt":
        raise RuntimeError("설치 검증은 Windows에서 실행해야 합니다.")
    setup = setup.resolve(strict=True)
    if installed_locations():
        raise RuntimeError("기존 제품 설치가 있어 자동 검증을 중단합니다. 덮어쓰지 않습니다.")
    running = application_running()
    if running != guard_only:
        raise RuntimeError(
            "실행 중 앱이 있어 설치 검증을 중단합니다."
            if running
            else "실행 차단 검증에는 먼저 앱을 실행해야 합니다."
        )
    test_id = str(uuid4())
    folder = ROOT / ".runtime" / "installer-tests" / test_id
    folder.mkdir(parents=True)
    destination = folder / "설치 폴더"
    data = folder / "사용자 데이터"
    media = folder / "녹화 보존 시험.bin"
    result = {"설치 파일 SHA256": hashlib.sha256(setup.read_bytes()).hexdigest(), "성공": False}
    common = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"]
    arguments = [
        str(setup),
        *common,
        f"/DIR={destination}",
        f"/GROUP=YouTube Live Recorder 검증 {test_id}",
        "/TASKS=",
    ]
    report = folder / "result.json"

    def save():
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        first = run([*arguments, f"/LOG={folder / 'install.log'}"])
        result["설치 반환 코드"] = first.returncode
        if guard_only:
            result["실행 중 설치 차단"] = bool(
                first.returncode != 0 and not destination.exists() and not installed_locations()
            )
            result["성공"] = result["실행 중 설치 차단"]
            if not result["성공"]:
                raise RuntimeError("실행 중 설치가 차단되지 않았습니다. 로그를 확인하세요.")
            return report
        if first.returncode:
            raise RuntimeError("설치에 실패했습니다. install.log를 확인하세요.")
        result["번들 검증"] = verify(destination, folder / "package-tests", qt_platform="windows")
        worker = destination / "YouTubeLiveRecorderWorker.exe"
        registered = run(
            [
                str(worker),
                "--data-dir",
                str(data),
                "add",
                "https://youtu.be/Abc_123-xYz",
                "--permission-confirmed",
                "--filename",
                "설치 후에도 유지되는 이름",
            ]
        )
        if registered.returncode:
            raise RuntimeError("설치한 프로그램의 대기 등록에 실패했습니다.")
        media.write_bytes(b"user-owned-recording-preservation-test")
        original = database_state(data / "data" / "app.db")
        original_media = media.read_bytes()
        reinstall = run([*arguments, f"/LOG={folder / 'reinstall.log'}"])
        result["재설치 반환 코드"] = reinstall.returncode
        if reinstall.returncode or database_state(data / "data" / "app.db") != original:
            raise RuntimeError("재설치 또는 사용자 DB 보존 검사에 실패했습니다.")
        result["재설치 후 데이터 보존"] = media.read_bytes() == original_media
        locations = installed_locations()
        if not locations or any(path != destination.resolve() for path in locations):
            raise RuntimeError("설치 경로가 바뀌었습니다. 자동 제거를 중단합니다.")
        uninstalled = run(
            [
                str(destination / "unins000.exe"),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                f"/LOG={folder / 'uninstall.log'}",
            ]
        )
        result["제거 반환 코드"] = uninstalled.returncode
        deadline = time.monotonic() + 30
        while worker.exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        result["제거 후 데이터 보존"] = (
            database_state(data / "data" / "app.db") == original
            and media.read_bytes() == original_media
        )
        result["성공"] = bool(
            uninstalled.returncode == 0
            and not worker.exists()
            and not installed_locations()
            and result["재설치 후 데이터 보존"]
            and result["제거 후 데이터 보존"]
        )
        if not result["성공"]:
            raise RuntimeError("설치 검증 중 실패한 항목이 있습니다.")
        return report
    finally:
        save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Windows 설치·재설치·제거와 사용자 데이터 보존 검사"
    )
    parser.add_argument(
        "--setup", type=Path, default=ROOT / "dist/installer/YouTubeLiveRecorder-0.3.4-Setup.exe"
    )
    parser.add_argument(
        "--running-guard-only", action="store_true", help="실행 중 설치 차단만 검사"
    )
    args = parser.parse_args()
    print(verify_installer(args.setup, guard_only=args.running_guard_only))
