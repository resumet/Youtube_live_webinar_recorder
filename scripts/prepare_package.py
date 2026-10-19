"""설치된 고정 의존성에서 도구·라이선스·아이콘을 빌드 디렉터리로 모은다."""

import importlib.metadata
import json
import os
import shutil
import subprocess
from pathlib import Path

from youtube_live_recorder.services.toolchain import Toolchain

ROOT = Path(__file__).resolve().parents[1]


def prepare() -> Path:
    resources = ROOT / "build" / "package-resources"
    licenses = resources / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    chain = Toolchain.discover()
    ffmpeg_folder = resources / "tools" / "ffmpeg"
    ffmpeg_folder.mkdir(parents=True, exist_ok=True)
    for source in chain.ffmpeg.parent.iterdir():
        if source.suffix.lower() == ".dll" or source.name in {"ffmpeg.exe", "ffprobe.exe"}:
            shutil.copy2(source, ffmpeg_folder / source.name)
    shutil.copy2(chain.ffmpeg.parent.parent / "LICENSE.txt", licenses / "FFmpeg-LGPL.txt")
    if chain.javascript_kind != "deno":
        raise SystemExit("고정된 Deno를 설치한 뒤 패키징하세요.")
    deno_folder = resources / "tools" / "deno"
    deno_folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(chain.javascript, deno_folder / "deno.exe")
    shutil.copy2(
        ROOT / "packaging" / "licenses" / "Deno-LICENSE.txt", licenses / "Deno-LICENSE.txt"
    )
    versions = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata["Name"]
        versions[name] = dist.version
        for item in dist.files or ():
            if any(word in str(item).lower() for word in ("license", "copying", "notice")):
                source = dist.locate_file(item)
                if source.is_file() and ".dist-info/" in str(item).replace("\\", "/"):
                    destination = licenses / name / str(item).split(".dist-info/", 1)[-1]
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
    # CPython embeddable runtime의 라이선스도 설치물에 포함한다.
    python_root = Path(__import__("sys").base_prefix)
    if (python_root / "LICENSE.txt").is_file():
        shutil.copy2(python_root / "LICENSE.txt", licenses / "Python-LICENSE.txt")
    (resources / "build-versions.json").write_text(
        json.dumps(versions, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (resources / "ffmpeg-build.txt").write_bytes(
        subprocess.run([str(chain.ffmpeg), "-version"], capture_output=True, check=True).stdout
    )
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from youtube_live_recorder.ui.theme import status_icon

    app = QApplication.instance() or QApplication([])
    if not status_icon().pixmap(256, 256).save(str(resources / "app.ico"), "ICO"):
        raise SystemExit("프로그램 아이콘을 저장하지 못했습니다.")
    del app
    return resources


if __name__ == "__main__":
    print(prepare())
