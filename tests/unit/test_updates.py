import hashlib
import io
import json
from threading import Event

import pytest

from youtube_live_recorder.services.updates import Release, UpdateError, UpdateService, https_url


def manifest(content=b"MZfixture", **overrides):
    return json.dumps(
        {
            "version": "0.2.0",
            "download_url": "https://updates.example/Setup.exe",
            "sha256": hashlib.sha256(content).hexdigest(),
            "notes": "개선 사항",
            **overrides,
        }
    ).encode()


def test_release_version_check_and_missing_server(tmp_path):
    service = UpdateService(tmp_path, opener=lambda _: io.BytesIO(manifest()))
    assert service.check("https://updates.example/release.json", "0.1.0").version == "0.2.0"
    assert service.check("https://updates.example/release.json", "0.2.0") is None
    assert service.check("https://updates.example/release.json", "1.0.0") is None
    with pytest.raises(UpdateError, match="설정"):
        service.check("", "0.1.0")


@pytest.mark.parametrize(
    "url",
    [
        "http://updates.example/x",
        "file:///x",
        "https://u:p@host/x",
        "https://host:invalid/x",
        "https://host/\nfile",
        "https://",
    ],
)
def test_invalid_update_urls_rejected(url):
    with pytest.raises(UpdateError):
        https_url(url)


@pytest.mark.parametrize(
    "value",
    [
        manifest(version="../0.2.0"),
        manifest(sha256="bad"),
        manifest(download_url="http://host/x"),
        b"[]",
        b"not json",
    ],
)
def test_malformed_manifest_cannot_be_installed(value):
    with pytest.raises(UpdateError):
        Release.parse(value)


def test_good_download_is_atomic_and_changed_installer_rejected(tmp_path):
    content = b"MZfixture"
    release = Release.parse(manifest(content))
    service = UpdateService(tmp_path, opener=lambda _: io.BytesIO(content))
    path = service.download(release)
    assert path.read_bytes() == content
    assert not list(tmp_path.glob("*.part"))
    service.verify_installer(path, release)
    path.write_bytes(b"MZtampered")
    with pytest.raises(UpdateError, match="변경"):
        service.verify_installer(path, release)


@pytest.mark.parametrize("content", [b"MZcorrupt", b""])
def test_bad_hash_never_publishes_executable(tmp_path, content):
    service = UpdateService(tmp_path, opener=lambda _: io.BytesIO(content))
    with pytest.raises(UpdateError):
        service.download(Release.parse(manifest()))
    assert not list(tmp_path.iterdir())


def test_cancellation_and_non_pe_payload_are_rejected(tmp_path):
    stop = Event()
    stop.set()
    service = UpdateService(tmp_path, opener=lambda _: io.BytesIO(b"not exe"))
    with pytest.raises(UpdateError, match="중단"):
        service.download(Release.parse(manifest()), cancelled=stop)
    with pytest.raises(UpdateError, match="실행 파일"):
        service.download(Release.parse(manifest(b"not exe")))
    assert not list(tmp_path.glob("*.exe"))
