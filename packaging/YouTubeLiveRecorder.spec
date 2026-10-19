# PyInstaller one-folder: GUI와 콘솔 워커가 동일한 Python/Qt 라이브러리를 공유한다.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent
resources = ROOT / "build" / "package-resources"
if not (resources / "app.ico").is_file():
    raise SystemExit("먼저 scripts/prepare_package.py를 실행하세요.")
datas = [(str(resources / "licenses"), "licenses"),
         (str(resources / "tools"), "tools"),
         (str(ROOT / "README.md"), "."),
         (str(ROOT / "docs"), "docs"),
         (str(ROOT / "docs" / "THIRD_PARTY.md"), "."),
         (str(resources / "build-versions.json"), "licenses"),
         (str(resources / "ffmpeg-build.txt"), "licenses"),
         (str(ROOT / "tools.lock.json"), "licenses")]
for package in ("yt_dlp", "yt_dlp_ejs", "tzdata", "certifi"):
    datas += collect_data_files(package)
for distribution in ("yt-dlp", "yt-dlp-ejs", "PySide6", "tzdata"):
    datas += copy_metadata(distribution)

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")], datas=datas,
    hiddenimports=collect_submodules("yt_dlp", filter=lambda n: ".__pyinstaller" not in n)
                  + collect_submodules("yt_dlp_ejs"),
    excludes=["pytest", "pytestqt", "ruff", "tkinter", "IPython", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)
options = [("X utf8", None, "OPTION")]
gui = EXE(pyz, a.scripts, options, exclude_binaries=True, name="YouTubeLiveRecorder",
          console=False, icon=str(resources / "app.ico"), upx=False,
          version=str(ROOT / "packaging" / "version_info.txt"))
worker = EXE(pyz, a.scripts, options, exclude_binaries=True, name="YouTubeLiveRecorderWorker",
             console=True, icon=str(resources / "app.ico"), upx=False,
             version=str(ROOT / "packaging" / "version_info.txt"))
coll = COLLECT(gui, worker, a.binaries, a.datas, name="YouTubeLiveRecorder", upx=False)
