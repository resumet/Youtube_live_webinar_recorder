import os
import subprocess
import sys

from youtube_live_recorder.bootstrap import bootstrap
from youtube_live_recorder.main import main


def test_bootstrap_uses_requested_root_and_persists_settings(tmp_path):
    context = bootstrap(tmp_path / "앱 데이터")
    assert context.paths.database.exists()
    assert (context.paths.logs / "app.log").exists()
    context.repository.set_setting("save_folder", str(tmp_path / "외장 드라이브"))
    restored = bootstrap(tmp_path / "앱 데이터")
    assert restored.settings.save_folder == tmp_path / "외장 드라이브"
    for handler in restored.logger.handlers[:]:
        restored.logger.removeHandler(handler)
        handler.close()


def test_cli_new_process_restores_queue(tmp_path):
    env = os.environ.copy()
    # 한국어 Windows 기본 파이프 인코딩에서도 CLI는 UTF-8로 출력해야 한다.
    env["PYTHONIOENCODING"] = "cp949"
    command = [sys.executable, "-m", "youtube_live_recorder", "--data-dir", str(tmp_path)]

    def run(*arguments):
        return subprocess.run(
            [*command, *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=20,
            check=False,
        )

    initialized = run("init")
    assert initialized.returncode == 0, initialized.stderr
    added = run("add", "https://youtu.be/Abc_123-xYz", "--permission-confirmed")
    assert added.returncode == 0, added.stderr
    restored = run("list")
    assert restored.returncode == 0
    assert "Abc_123-xYz" in restored.stdout and "방송 대기" in restored.stdout
    duplicate = run("add", "https://youtube.com/live/Abc_123-xYz", "--permission-confirmed")
    assert duplicate.returncode == 2
    assert "이미 대기" in duplicate.stderr


def test_empty_launch_does_not_modify_data(tmp_path, monkeypatch, capsys):
    target = tmp_path / "not-created"
    monkeypatch.setenv("YLR_DATA_DIR", str(target))
    assert main([]) == 0
    assert not target.exists()
    assert "사용 가능한 명령" in capsys.readouterr().out
