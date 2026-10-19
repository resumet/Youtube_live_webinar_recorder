import ctypes
import logging
import os

LOGGER = logging.getLogger(__name__)
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


class PowerManager:
    """활성화와 해제는 반드시 동일한 엔진 스레드에서 호출한다."""

    def __init__(self, setter=None):
        self.required = False
        self.warned = False
        self.setter = setter
        if setter is None and os.name == "nt":
            self.setter = ctypes.WinDLL("kernel32", use_last_error=True).SetThreadExecutionState
            self.setter.argtypes = [ctypes.c_ulong]
            self.setter.restype = ctypes.c_ulong

    def set_required(self, required: bool) -> None:
        if required == self.required:
            return
        flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if required else 0)
        if self.setter and not self.setter(flags):
            if not self.warned:
                LOGGER.warning(
                    "자동 절전 방지를 설정하지 못했습니다. Windows 전원 설정을 확인하세요."
                )
                self.warned = True
            return
        self.required = required

    def close(self) -> None:
        self.set_required(False)
