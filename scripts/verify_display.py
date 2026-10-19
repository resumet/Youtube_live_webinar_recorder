"""Qt의 배율 시뮬레이션으로 실제 Windows 번들의 네 화면을 렌더링한다."""

import argparse
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4


def verify_display(bundle: Path, reports: Path) -> Path:
    if os.name != "nt":
        raise RuntimeError("Windows 화면 배율 검증은 Windows에서 실행하세요.")
    app = (bundle.resolve() / "YouTubeLiveRecorder.exe").resolve(strict=True)
    root = reports.resolve() / str(uuid4())
    root.mkdir(parents=True)
    results = []
    env = os.environ.copy()
    for name in (
        "PYTHONPATH",
        "YLR_TOOLS_DIR",
        "YLR_UPDATE_MANIFEST_URL",
        "QT_SCREEN_SCALE_FACTORS",
    ):
        env.pop(name, None)
    env["QT_QPA_PLATFORM"] = "windows"
    env["PATH"] = str(Path(env.get("WINDIR", "C:/Windows")) / "System32")
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    for scale in ("1", "1.25", "1.5", "2"):
        folder = root / scale
        report = folder / "display.json"
        process = subprocess.run(
            [str(app), "--data-dir", str(folder), "gui", "--smoke-report", str(report)],
            env={**env, "QT_SCALE_FACTOR": scale},
            timeout=60,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            startupinfo=startup,
        )
        if process.returncode or not report.is_file():
            raise RuntimeError(f"Qt 배율 {scale}에서 번들 실행에 실패했습니다.")
        result = json.loads(report.read_text(encoding="utf-8"))
        results.append({"요청 Qt 배율": scale, **result})
    summary = {
        "성공": all(
            result["성공"]
            and result.get("화면 안에 창 표시")
            and len(result.get("페이지", [])) == 4
            for result in results
        ),
        "범위": "Windows 네이티브 Qt · 프로세스별 Qt 배율 시뮬레이션, OS 설정 변경 없음",
        "결과": results,
    }
    summary_path = root / "result.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if not summary["성공"]:
        raise RuntimeError(f"화면 검사에 통과하지 못했습니다. 결과: {summary_path}")
    return summary_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Windows 번들의 100/125/150/200% Qt 배율 검사")
    parser.add_argument("--bundle", type=Path, default=Path("dist/YouTubeLiveRecorder"))
    parser.add_argument("--reports", type=Path, default=Path(".runtime/display-tests"))
    args = parser.parse_args()
    print(verify_display(args.bundle, args.reports))
