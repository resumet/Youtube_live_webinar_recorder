import ctypes
import os
import uuid
from pathlib import Path


def videos_folder() -> Path:
    """사용자가 이동한 동영상 폴더를 따르며 OS 조회 실패 시 기본 경로를 쓴다."""
    fallback = Path.home() / "Videos"
    if os.name != "nt":
        return fallback
    ole = ctypes.OleDLL("ole32")
    shell = ctypes.OleDLL("shell32")
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.restype = None
    shell.SHGetKnownFolderPath.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    initialized = False
    pointer = ctypes.c_wchar_p()
    try:
        # RPC_E_CHANGED_MODE는 이미 다른 모드로 초기화된 스레드. 기존 COM 모드를 유지한다.
        try:
            initialized = ole.CoInitializeEx(None, 2) in (0, 1)
        except OSError:
            pass
        guid = ctypes.create_string_buffer(
            uuid.UUID("18989b1d-99b5-455b-841c-ab7c74e4ddfc").bytes_le
        )
        # KF_FLAG_DONT_VERIFY: 아직 생성되지 않은 동영상 경로도 조회한다.
        result = shell.SHGetKnownFolderPath(guid, 0x4000, None, ctypes.byref(pointer))
        return Path(pointer.value) if result == 0 and pointer.value else fallback
    except OSError:
        return fallback
    finally:
        if pointer:
            ole.CoTaskMemFree(pointer)
        if initialized:
            ole.CoUninitialize()
