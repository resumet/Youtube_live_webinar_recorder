from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_URL = "INVALID_URL"
    DUPLICATE_BROADCAST = "DUPLICATE_BROADCAST"
    INVALID_STATE = "INVALID_STATE"
    PERMISSION_REQUIRED = "PERMISSION_REQUIRED"
    NETWORK_DISCONNECTED = "NETWORK_DISCONNECTED"
    STREAM_NOT_LIVE = "STREAM_NOT_LIVE"
    STREAM_UNAVAILABLE = "STREAM_UNAVAILABLE"
    STREAM_ENDED = "STREAM_ENDED"
    BUSY_SINGLE_SLOT = "BUSY_SINGLE_SLOT"
    DISK_LOW = "DISK_LOW"
    WRITE_PERMISSION_DENIED = "WRITE_PERMISSION_DENIED"
    MEDIA_TOOL_MISSING = "MEDIA_TOOL_MISSING"
    FINALIZE_FAILED = "FINALIZE_FAILED"
    VERIFY_FAILED = "VERIFY_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    REPLAY_EXPIRED = "REPLAY_EXPIRED"
    DVR_UNAVAILABLE = "DVR_UNAVAILABLE"
    FORMAT_UNAVAILABLE = "FORMAT_UNAVAILABLE"


MESSAGES = {
    ErrorCode.DVR_UNAVAILABLE: "방송 시작 구간을 가져올 수 없어 현재 시점부터 저장을 시도합니다.",
    ErrorCode.FORMAT_UNAVAILABLE: "요청한 조건으로 저장 가능한 영상·음성 형식이 없습니다.",
    ErrorCode.INVALID_URL: "유효한 YouTube 영상 URL을 입력해 주세요.",
    ErrorCode.DUPLICATE_BROADCAST: "이미 대기 또는 진행 중인 방송입니다.",
    ErrorCode.INVALID_STATE: "현재 상태에서는 이 작업을 수행할 수 없습니다.",
    ErrorCode.PERMISSION_REQUIRED: "이 콘텐츠를 녹화하고 저장할 권한을 확인해 주세요.",
    ErrorCode.NETWORK_DISCONNECTED: "인터넷 연결을 확인해 주세요. 자동으로 재시도합니다.",
    ErrorCode.STREAM_NOT_LIVE: "아직 방송이 시작되지 않았습니다.",
    ErrorCode.STREAM_UNAVAILABLE: (
        "방송을 볼 수 없거나 접근할 수 없습니다. 제한을 우회하지 않습니다."
    ),
    ErrorCode.STREAM_ENDED: "방송이 종료되었습니다.",
    ErrorCode.BUSY_SINGLE_SLOT: "다른 방송을 녹화하거나 저장하고 있습니다.",
    ErrorCode.DISK_LOW: "저장 공간이 부족합니다. 공간을 확보해 주세요.",
    ErrorCode.WRITE_PERMISSION_DENIED: "저장 폴더에 쓸 수 없습니다. 저장 위치를 확인해 주세요.",
    ErrorCode.MEDIA_TOOL_MISSING: "녹화 구성요소가 없습니다. 설치 상태를 확인해 주세요.",
    ErrorCode.FINALIZE_FAILED: "영상 파일 저장 중 오류가 발생했습니다. 임시 파일은 보존됩니다.",
    ErrorCode.VERIFY_FAILED: "저장된 파일이 기본 검사를 통과하지 못했습니다.",
    ErrorCode.RATE_LIMITED: "요청이 일시적으로 제한되었습니다. 잠시 후 다시 확인합니다.",
    ErrorCode.REPLAY_EXPIRED: "24시간 내 다시보기를 찾지 못했습니다.",
}


class AppError(Exception):
    def __init__(self, code: ErrorCode, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(MESSAGES[code])
