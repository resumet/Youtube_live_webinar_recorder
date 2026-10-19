import os
import re
from datetime import datetime
from pathlib import Path

from youtube_live_recorder.utils.time import seoul_time

_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", re.IGNORECASE)


def safe_stem(value: str, max_units: int = 140) -> str:
    name = _FORBIDDEN.sub("_", value).strip(" .")
    if name.lower().endswith(".mp4"):
        name = name[:-4].rstrip(" .")
    if _RESERVED.match(name):
        name = "_" + name
    while len(name.encode("utf-16-le")) // 2 > max_units:
        name = name[:-1]
    return name.rstrip(" .") or "방송"


def recording_name(
    title: str, started_at: datetime, custom: str = "", *, replay: bool = False
) -> str:
    base = custom or f"{seoul_time(started_at):%Y-%m-%d}_{title}"
    stem = safe_stem(base)
    return stem + ("_다시보기" if replay else "") + ".mp4"


def reserve_output(folder: Path, name: str) -> Path:
    """별도 .reserve 파일로 예약한다. 미완성 데이터를 .mp4로 노출하지 않는다."""
    folder = folder.resolve()
    remaining = 235 - len(str(folder).encode("utf-16-le")) // 2 - 12
    if remaining < 10:
        raise OSError("저장 경로가 너무 깁니다. 더 짧은 폴더를 선택해 주세요.")
    stem = safe_stem(name, min(140, remaining))
    for index in range(1, 10000):
        suffix = "" if index == 1 else f" ({index})"
        target = folder / f"{stem}{suffix}.mp4"
        if target.exists():
            continue
        try:
            descriptor = os.open(
                reservation_marker(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
            )
            os.close(descriptor)
            return target
        except FileExistsError:
            continue
    raise OSError("동일한 파일명이 너무 많습니다. 다른 이름을 선택해 주세요.")


def reservation_marker(path: Path) -> Path:
    return path.with_name(path.name + ".reserve")
