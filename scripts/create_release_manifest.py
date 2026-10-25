"""GitHub Release용 업데이트 매니페스트를 생성한다."""

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "resumet/Youtube_live_webinar_recorder"


def project_version() -> str:
    content = (ROOT / "src/youtube_live_recorder/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "(\d+\.\d+\.\d+)"$', content, re.MULTILINE)
    if not match:
        raise RuntimeError("프로그램 버전을 찾을 수 없습니다.")
    return match.group(1)


def create_manifest(setup: Path, notes: str) -> Path:
    version = project_version()
    expected_name = f"YouTubeLiveRecorder-{version}-Setup.exe"
    if setup.name != expected_name or not setup.is_file():
        raise FileNotFoundError(f"릴리스 설치 파일이 없습니다: {expected_name}")
    with setup.open("rb") as handle:
        checksum = hashlib.file_digest(handle, "sha256").hexdigest()
    manifest = {
        "version": version,
        "download_url": (
            f"https://github.com/{REPOSITORY}/releases/download/v{version}/{expected_name}"
        ),
        "sha256": checksum,
        "notes": notes,
    }
    destination = setup.parent / "release.json"
    destination.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", type=Path, required=True)
    parser.add_argument(
        "--notes",
        default="상단 메뉴, 프로그램 정보, GitHub Release 기반 자동 업데이트를 추가했습니다.",
    )
    arguments = parser.parse_args()
    print(create_manifest(arguments.setup.resolve(), arguments.notes))
