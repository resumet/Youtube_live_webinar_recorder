import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from youtube_live_recorder.utils.errors import AppError, ErrorCode


@dataclass(frozen=True)
class Toolchain:
    ffmpeg: Path
    ffprobe: Path
    javascript: Path
    javascript_kind: str = "deno"

    @classmethod
    def discover(cls) -> "Toolchain":
        roots = [Path(sys.executable).parent / "tools"]
        if getattr(sys, "frozen", False):
            roots.insert(0, Path(sys._MEIPASS) / "tools")
        else:
            roots.insert(0, Path(__file__).resolve().parents[3] / ".tools")
        if os.environ.get("YLR_TOOLS_DIR"):
            roots.insert(0, Path(os.environ["YLR_TOOLS_DIR"]))

        def locate(name: str) -> Path | None:
            for root in roots:
                if root.is_dir():
                    found = sorted(root.glob(f"**/{name}.exe"))
                    if found:
                        return found[0].resolve()
            path = shutil.which(name)
            return Path(path).resolve() if path else None

        ffmpeg, ffprobe = locate("ffmpeg"), locate("ffprobe")
        javascript = locate("deno")
        kind = "deno"
        if not javascript:
            javascript, kind = locate("node"), "node"
        if not all((ffmpeg, ffprobe, javascript)):
            raise AppError(ErrorCode.MEDIA_TOOL_MISSING)
        return cls(ffmpeg, ffprobe, javascript, kind)
