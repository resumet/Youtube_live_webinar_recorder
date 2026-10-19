import shutil
import tempfile
from pathlib import Path

from youtube_live_recorder.utils.errors import AppError, ErrorCode


def check_storage(folder: Path, minimum: int, *, create: bool = False) -> int:
    try:
        if create:
            folder.mkdir(parents=True, exist_ok=True)
        if not folder.is_dir():
            raise OSError("저장 폴더가 없습니다.")
        free = shutil.disk_usage(folder).free
        if free < minimum:
            raise AppError(ErrorCode.DISK_LOW)
        with tempfile.TemporaryFile(dir=folder) as handle:
            handle.write(b"test")
            handle.flush()
        return free
    except OSError:
        raise AppError(ErrorCode.WRITE_PERMISSION_DENIED) from None
