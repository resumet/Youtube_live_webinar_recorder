import hashlib
import json
import os
import re
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

MAX_INSTALLER_BYTES = 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024


class UpdateError(Exception):
    pass


def https_url(value: str) -> str:
    if not isinstance(value, str) or any(ord(char) < 33 for char in value):
        raise UpdateError("업데이트 주소는 사용자 정보가 없는 HTTPS URL이어야 합니다.")
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or (port is not None and not 0 < port <= 65535)
        ):
            raise ValueError
    except ValueError:
        raise UpdateError("업데이트 주소는 사용자 정보가 없는 HTTPS URL이어야 합니다.") from None
    return value


class SecureRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        https_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def secure_open(url: str):
    request = urllib.request.Request(https_url(url), headers={"User-Agent": "YouTubeLiveRecorder"})
    return urllib.request.build_opener(SecureRedirect()).open(request, timeout=15)


def version_tuple(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,5}\.\d{1,5}\.\d{1,5}", value):
        raise UpdateError("업데이트 버전 형식을 확인할 수 없습니다.")
    return tuple(int(part) for part in value.split("."))


@dataclass(frozen=True)
class Release:
    version: str
    download_url: str
    sha256: str
    notes: str = ""

    @classmethod
    def parse(cls, data: bytes) -> "Release":
        try:
            value = json.loads(data)
            version = value["version"]
            version_tuple(version)
            url = https_url(value["download_url"])
            checksum = value["sha256"]
            if not isinstance(checksum, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", checksum):
                raise ValueError
            notes = value.get("notes", "")
            if not isinstance(notes, str) or len(notes) > 16000:
                raise ValueError
            return cls(version, url, checksum.lower(), notes)
        except (KeyError, TypeError, ValueError, AttributeError):
            raise UpdateError("업데이트 정보 형식 또는 파일 해시를 확인할 수 없습니다.") from None


class UpdateService:
    def __init__(self, cache: Path, *, opener=secure_open):
        self.cache, self.opener = cache, opener

    def check(self, manifest_url: str, current_version: str) -> Release | None:
        if not manifest_url:
            raise UpdateError("업데이트 배포 주소가 아직 설정되지 않았습니다.")
        https_url(manifest_url)
        try:
            with self.opener(manifest_url) as response:
                data = response.read(MAX_MANIFEST_BYTES + 1)
            if len(data) > MAX_MANIFEST_BYTES:
                raise UpdateError("업데이트 정보가 허용 크기를 초과했습니다.")
            release = Release.parse(data)
        except OSError:
            raise UpdateError(
                "업데이트 정보를 가져오지 못했습니다. 인터넷 연결을 확인해 주세요."
            ) from None
        return release if version_tuple(release.version) > version_tuple(current_version) else None

    def download(self, release: Release, *, cancelled=None) -> Path:
        version_tuple(release.version)
        https_url(release.download_url)
        if cancelled is not None and cancelled.is_set():
            raise UpdateError("업데이트 다운로드를 중단했습니다.")
        self.cache.mkdir(parents=True, exist_ok=True)
        destination = self.cache / f"YouTubeLiveRecorder-{release.version}-Setup.exe"
        fd, temp_name = tempfile.mkstemp(prefix="installer-", suffix=".part", dir=self.cache)
        temporary = Path(temp_name)
        checksum = hashlib.sha256()
        size = 0
        try:
            with os.fdopen(fd, "wb") as output, self.opener(release.download_url) as response:
                while chunk := response.read(128 * 1024):
                    if cancelled is not None and cancelled.is_set():
                        raise UpdateError("업데이트 다운로드를 중단했습니다.")
                    size += len(chunk)
                    if size > MAX_INSTALLER_BYTES:
                        raise UpdateError("업데이트 파일이 허용 크기를 초과했습니다.")
                    output.write(chunk)
                    checksum.update(chunk)
                output.flush()
                os.fsync(output.fileno())
            if not size or checksum.hexdigest() != release.sha256:
                raise UpdateError("업데이트 파일의 무결성 검사에 실패했습니다. 설치하지 않습니다.")
            with temporary.open("rb") as header:
                if header.read(2) != b"MZ":
                    raise UpdateError("Windows 설치 실행 파일을 확인할 수 없습니다.")
            os.replace(temporary, destination)
            return destination
        except OSError:
            raise UpdateError(
                "업데이트 파일을 저장하지 못했습니다. 네트워크와 저장 공간을 확인하세요."
            ) from None
        finally:
            temporary.unlink(missing_ok=True)

    def verify_installer(self, path: Path, release: Release) -> None:
        if path.resolve().parent != self.cache.resolve() or path.suffix.lower() != ".exe":
            raise UpdateError("확인되지 않은 설치 파일 경로입니다.")
        try:
            with path.open("rb") as handle:
                checksum = hashlib.file_digest(handle, "sha256").hexdigest()
        except OSError:
            raise UpdateError("다운로드한 설치 파일을 읽을 수 없습니다.") from None
        if checksum != release.sha256:
            raise UpdateError("다운로드 후 설치 파일이 변경되었습니다. 다시 다운로드해 주세요.")
