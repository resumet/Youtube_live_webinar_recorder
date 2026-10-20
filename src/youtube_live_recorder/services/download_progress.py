"""Small, URL-free yt-dlp events aggregated across selected video/audio formats."""

import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

PLAN_TEMPLATE = (
    'before_dl:YLR_PLAN {"duration":%(duration|null)j,'
    '"formats":%(requested_formats.:.{format_id,filesize,filesize_approx,tbr})j,'
    '"format":%(.{format_id,filesize,filesize_approx,tbr})j}'
)
PROGRESS_TEMPLATE = (
    'download:YLR_PROGRESS {"format_id":%(info.format_id|null)j,'
    '"status":%(progress.status|null)j,"downloaded":%(progress.downloaded_bytes|null)j,'
    '"total":%(progress.total_bytes|null)j,"estimate":%(progress.total_bytes_estimate|null)j,'
    '"speed":%(progress.speed|null)j}'
)


def _number(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(value) and 0 <= value < 1e30:
            return float(value)
    return None


@dataclass(frozen=True)
class DownloadProgress:
    downloaded_bytes: int
    total_bytes: int | None
    percent: float | None
    speed_bytes_per_second: float | None
    eta_seconds: float | None
    estimated: bool
    transfer_finished: bool
    updated_at: float

    def is_stale(self, now: float | None = None) -> bool:
        return (time.monotonic() if now is None else now) - self.updated_at > 15


@dataclass
class _Part:
    downloaded: int = 0
    total: int | None = None
    estimated: bool = True
    finished: bool = False


class ProgressTracker:
    def __init__(self, callback: Callable[[DownloadProgress], None], *, clock=time.monotonic):
        self.callback, self.clock = callback, clock
        self.lock = Lock()
        self.parts: dict[str, _Part] = {}
        self.expected: set[str] = set()
        self.speed = None
        self.updated_at = clock()

    def feed(self, line: str) -> bool:
        """Consume either output stream; malformed events must not stop a download."""
        prefix, _, payload = line.strip().partition(" ")
        if prefix not in {"YLR_PLAN", "YLR_PROGRESS"}:
            return False
        try:
            data = json.loads(payload)
        except (ValueError, TypeError):
            return True
        if not isinstance(data, dict):
            return True
        with self.lock:
            if prefix == "YLR_PLAN":
                self._plan(data)
            else:
                self._progress(data)
            self.callback(self._snapshot())
        return True

    def _plan(self, data):
        formats = data.get("formats")
        if not isinstance(formats, list) or not formats:
            formats = [data.get("format")]
        duration = _number(data.get("duration"))
        for fmt in formats:
            if not isinstance(fmt, dict) or not isinstance(fmt.get("format_id"), str):
                continue
            identifier = fmt["format_id"]
            self.expected.add(identifier)
            part = self.parts.setdefault(identifier, _Part())
            # stdout plan can arrive after stderr progress: never replace observed sizes.
            if part.total is not None or part.finished:
                continue
            exact = _number(fmt.get("filesize"))
            approximate = _number(fmt.get("filesize_approx"))
            bitrate = _number(fmt.get("tbr"))
            total = (
                exact or approximate or (duration * bitrate * 125 if duration and bitrate else 0)
            )
            if total:
                part.total = int(total)
                part.estimated = not bool(exact)

    def _progress(self, data):
        identifier, status = data.get("format_id"), data.get("status")
        downloaded = _number(data.get("downloaded"))
        if (
            not isinstance(identifier, str)
            or status not in {"downloading", "finished"}
            or downloaded is None
        ):
            return
        part = self.parts.setdefault(identifier, _Part())
        # A repeated finish notification counts the same format only once.
        part.downloaded = int(downloaded)
        exact, approximate = _number(data.get("total")), _number(data.get("estimate"))
        if status == "finished":
            part.total, part.finished, part.estimated = part.downloaded, True, False
        elif exact or approximate:
            part.total, part.estimated = int(exact or approximate), not bool(exact)
        self.speed = _number(data.get("speed")) or None
        self.updated_at = self.clock()

    def _snapshot(self) -> DownloadProgress:
        parts = list(self.parts.values())
        downloaded = sum(p.downloaded for p in parts)
        known = bool(self.expected) and all(p.total is not None for p in parts)
        total = sum(max(p.total, p.downloaded) for p in parts) if known else None
        finished = bool(self.expected) and all(p.finished for p in parts)
        percent = 100.0 if finished else min(99.9, downloaded / total * 100) if total else None
        eta = (
            (total - downloaded) / self.speed
            if total and total > downloaded and self.speed
            else None
        )
        if eta is not None and not math.isfinite(eta):
            eta = None
        return DownloadProgress(
            downloaded,
            total,
            percent,
            self.speed,
            0 if finished else eta,
            any(p.estimated for p in parts),
            finished,
            self.updated_at,
        )
