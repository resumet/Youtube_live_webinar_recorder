"""소스 Python 없이 번들 실행 파일로 진단·미디어·Qt 종료 경로를 검증한다."""

import argparse
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4


def verify(bundle: Path, reports: Path, *, qt_platform: str = "offscreen") -> dict:
    bundle, reports = bundle.resolve(), reports.resolve()
    reports.mkdir(parents=True, exist_ok=True)
    run = reports / str(uuid4())
    worker = bundle / "YouTubeLiveRecorderWorker.exe"
    app = bundle / "YouTubeLiveRecorder.exe"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("YLR_TOOLS_DIR", None)
    env.pop("YLR_UPDATE_MANIFEST_URL", None)
    env["QT_QPA_PLATFORM"] = qt_platform
    # 시스템 FFmpeg/Node/Python이 없는 조건에서 번들 의존성만 사용하게 한다.
    env["PATH"] = str(Path(env.get("WINDIR", "C:/Windows")) / "System32")
    options = {
        "env": env,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "creationflags": subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    }
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        options["startupinfo"] = startup
    checks = {"Qt 플랫폼": qt_platform}
    for command in ("diagnose", "self-test"):
        result = subprocess.run(
            [str(worker), "--data-dir", str(run), command], timeout=180, **options
        )
        if result.returncode:
            raise RuntimeError(f"번들 {command} 실패: {result.stderr[-1000:]}")
        checks[command] = json.loads(result.stdout)
    gui_report = run / "gui-result.json"
    result = subprocess.run(
        [str(app), "--data-dir", str(run), "gui", "--smoke-report", str(gui_report)],
        timeout=60,
        **options,
    )
    if result.returncode or not gui_report.is_file():
        raise RuntimeError("번들 GUI 실행/종료에 실패했습니다.")
    checks["gui"] = json.loads(gui_report.read_text(encoding="utf-8"))
    if not checks["self-test"]["성공"] or not checks["gui"]["성공"]:
        raise RuntimeError("번들 검증 항목이 통과하지 못했습니다.")
    (run / "package-result.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"성공": True, "결과": str(run / "package-result.json")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Windows 패키지 실행 검증")
    parser.add_argument("--bundle", type=Path, default=Path("dist/YouTubeLiveRecorder"))
    parser.add_argument("--reports", type=Path, default=Path(".runtime/package-tests"))
    parser.add_argument("--qt-platform", choices=("offscreen", "windows"), default="offscreen")
    args = parser.parse_args()
    print(
        json.dumps(
            verify(args.bundle, args.reports, qt_platform=args.qt_platform), ensure_ascii=False
        )
    )
