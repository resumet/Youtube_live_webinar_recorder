from youtube_live_recorder.data.models import Broadcast, Quality
from youtube_live_recorder.data.repository import Repository
from youtube_live_recorder.services.interfaces import MetadataProvider
from youtube_live_recorder.utils.errors import AppError, ErrorCode
from youtube_live_recorder.utils.urls import parse_video_url


class ArchiveDownloads:
    """종료된 라이브를 확인한 뒤 영속 다운로드 대기열에 등록한다. 작업 스레드에서 호출한다."""

    def __init__(self, repository: Repository, metadata: MetadataProvider):
        self.repository, self.metadata = repository, metadata

    def register(
        self,
        url: str,
        *,
        permission_confirmed: bool,
        quality: Quality = Quality.P1080,
        custom_filename: str = "",
    ) -> Broadcast:
        parsed = parse_video_url(url)
        if permission_confirmed is not True:
            raise AppError(ErrorCode.PERMISSION_REQUIRED)
        metadata = self.metadata.fetch(parsed.canonical_url)
        return self.repository.add_broadcast(
            parsed.canonical_url,
            permission_confirmed=True,
            quality=quality,
            custom_filename=custom_filename,
            archive_metadata=metadata,
        )
