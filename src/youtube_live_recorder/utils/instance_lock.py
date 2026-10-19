import os
from pathlib import Path


class InstanceLock:
    """프로세스 종료 시 운영체제가 해제하는 데이터 폴더별 배타적 잠금."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.file = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        if stream.seek(0, 2) == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            raise RuntimeError("이 데이터 폴더로 실행 중인 프로그램이 있습니다.") from None
        self.file = stream

    def release(self) -> None:
        if self.file:
            self.file.close()
            self.file = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_):
        self.release()
