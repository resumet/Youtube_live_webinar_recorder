"""고정한 배포 파일의 해시를 검증한 다음 프로젝트 .tools에 압축 해제한다."""

import hashlib
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    lock = json.loads((ROOT / "tools.lock.json").read_text(encoding="utf-8"))
    cache = ROOT / ".cache" / "downloads"
    cache.mkdir(parents=True, exist_ok=True)
    for name, tool in lock.items():
        archive = cache / f"{name}-{tool['sha256'][:12]}.zip"
        if not archive.exists():
            request = urllib.request.Request(
                tool["url"], headers={"User-Agent": "YouTubeLiveRecorder"}
            )
            with (
                urllib.request.urlopen(request, timeout=60) as response,
                archive.open("wb") as dest,
            ):
                shutil.copyfileobj(response, dest)
        with archive.open("rb") as downloaded:
            actual = hashlib.file_digest(downloaded, "sha256").hexdigest()
        if actual != tool["sha256"]:
            raise RuntimeError(f"{name}: 다운로드 해시 불일치. 캐시를 확인하세요.")
        destination = (ROOT / ".tools" / tool["directory"]).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as package:
            for item in package.infolist():
                if not (destination / item.filename).resolve().is_relative_to(destination):
                    raise RuntimeError("압축 파일 경로가 대상 폴더를 벗어납니다.")
            package.extractall(destination)
        print(f"{name} {tool['version']}: SHA256 확인 및 설치 완료")


if __name__ == "__main__":
    main()
