DEFAULT_CONCURRENT_RECORDINGS = 5
MAX_CONCURRENT_RECORDINGS = 10


def validate_recording_limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= MAX_CONCURRENT_RECORDINGS:
        raise ValueError(f"동시 녹화 수는 1~{MAX_CONCURRENT_RECORDINGS}개로 설정해 주세요.")
    return value
