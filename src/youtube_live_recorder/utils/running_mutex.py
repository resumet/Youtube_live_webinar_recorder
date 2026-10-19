import ctypes
import os

_HANDLE = None


def mark_application_running() -> None:
    """설치·제거가 녹화 중인 프로그램을 덮어쓰지 않도록 Inno Setup에 알린다."""
    global _HANDLE
    if os.name != "nt" or _HANDLE:
        return
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    api.CreateMutexW.restype = ctypes.c_void_p
    _HANDLE = api.CreateMutexW(None, False, "Local\\YouTubeLiveRecorder.Running")
    if not _HANDLE:
        raise OSError("설치 보호 잠금을 만들 수 없습니다.")
    # 운영체제가 프로세스 종료 시 핸들을 닫는다. 설치 실행 직전에도 살아 있어야 한다.
