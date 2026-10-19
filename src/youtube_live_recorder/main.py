import argparse
import importlib.metadata
import json
import shutil
import sqlite3
import sys
from pathlib import Path

from youtube_live_recorder import __version__
from youtube_live_recorder.bootstrap import bootstrap
from youtube_live_recorder.data.migrations import SCHEMA_VERSION
from youtube_live_recorder.data.models import STATUS_LABELS, BroadcastStatus, Quality
from youtube_live_recorder.utils.errors import AppError


class KoreanParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs) -> None:
        kwargs["add_help"] = False
        super().__init__(*args, **kwargs)
        self._positionals.title = "명령"
        self._optionals.title = "옵션"
        self.add_argument("-h", "--help", action="help", help="사용법을 표시하고 종료")

    def format_usage(self) -> str:
        return super().format_usage().replace("usage:", "사용법:", 1)

    def format_help(self) -> str:
        return super().format_help().replace("usage:", "사용법:", 1)

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, "입력한 명령이나 옵션을 확인해 주세요. --help로 사용법을 볼 수 있습니다.\n")


def build_parser() -> argparse.ArgumentParser:
    parser = KoreanParser(description="YouTube Live Recorder · 초기화 및 엔진 진단 도구")
    parser._positionals.title = "명령"
    parser._optionals.title = "옵션"
    parser.add_argument("--version", action="version", version=f"프로그램 버전 {__version__}")
    parser.add_argument("--data-dir", type=Path, help="DB와 로그를 저장할 별도 폴더")
    commands = parser.add_subparsers(dest="command", title="사용 가능한 명령")
    commands.add_parser("init", help="DB와 기본 설정 초기화")
    commands.add_parser("diagnose", help="DB 및 외부 도구 설치 상태 확인")
    add = commands.add_parser("add", help="방송 대기 등록 (1단계에서는 자동 감지 미실행)")
    add.add_argument("url", help="YouTube 방송 URL")
    add.add_argument(
        "--quality", choices=[q.value for q in Quality], default="1080p", help="희망 화질"
    )
    add.add_argument("--filename", default="", help="사용자 지정 파일명")
    add.add_argument("--permission-confirmed", action="store_true", help="녹화 및 저장 권한 확인")
    commands.add_parser("list", help="저장된 대기 목록 확인")
    cancel = commands.add_parser("cancel", help="대기 방송 취소")
    cancel.add_argument("id", help="등록 UUID (list 명령으로 확인)")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        context = bootstrap(args.data_dir)
        if args.command == "init":
            print(f"초기화 완료 · 데이터베이스: {context.paths.database}")
            print(f"로그 폴더: {context.paths.logs}")
            print("현재는 1단계입니다. 자동 녹화 엔진과 GUI는 아직 실행되지 않습니다.")
        elif args.command == "diagnose":
            packages = {}
            for package in ("PySide6", "yt-dlp", "tzdata"):
                try:
                    packages[package] = importlib.metadata.version(package)
                except importlib.metadata.PackageNotFoundError:
                    packages[package] = "설치되지 않음"
            tools = {
                name: shutil.which(name) or "설치되지 않음"
                for name in ("ffmpeg", "ffprobe", "deno", "node")
            }
            print(
                json.dumps(
                    {
                        "프로그램 버전": __version__,
                        "Python": sys.version.split()[0],
                        "DB 스키마": SCHEMA_VERSION,
                        "DB 기본 검사": context.database.check_integrity(),
                        "데이터 폴더": str(context.paths.root),
                        "패키지": packages,
                        "외부 도구": tools,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args.command == "add":
            broadcast = context.repository.add_broadcast(
                args.url,
                permission_confirmed=args.permission_confirmed,
                quality=Quality(args.quality),
                custom_filename=args.filename,
            )
            print(f"대기 목록에 저장했습니다: {broadcast.id}")
            print("자동 감지는 아직 구현되지 않았습니다. 현재는 목록 저장만 수행합니다.")
        elif args.command == "list":
            broadcasts = context.repository.list_broadcasts()
            if not broadcasts:
                print("등록된 대기 방송이 없습니다.")
            for item in broadcasts:
                print(f"{item.id} | {item.title or item.video_id} | {STATUS_LABELS[item.status]}")
        elif args.command == "cancel":
            context.repository.transition(args.id, BroadcastStatus.CANCELLED)
            print("방송 대기를 취소했습니다.")
    except AppError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (OSError, RuntimeError, KeyError, sqlite3.DatabaseError):
        import logging

        logging.getLogger("youtube_live_recorder").exception("초기화 또는 명령 실행 실패")
        print("작업을 완료할 수 없습니다. 데이터 경로와 로그를 확인해 주세요.", file=sys.stderr)
        return 1
    return 0
