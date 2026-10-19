# 외부 구성요소 고지

YouTube Live Recorder는 다음 구성요소를 포함합니다. 설치 폴더 `_internal/licenses`에
배포 패키지에서 수집한 라이선스와 저작권 고지를 제공합니다. FFmpeg와 Qt는 별도 DLL로 포함하며
사용자가 호환되는 수정본으로 교체할 수 있습니다. 원래 녹화·DB 데이터는 설치 파일에 포함하지 않습니다.

| 구성요소 | 출처 | 고지 |
|---|---|---|
| CPython | https://www.python.org/ | PSF License |
| PySide6 / Qt / Shiboken6 | https://www.qt.io/qt-for-python | LGPLv3 등, 실제 포함 모듈의 고지 참조 |
| yt-dlp / yt-dlp-ejs | https://github.com/yt-dlp/yt-dlp | 설치된 배포본의 LICENSE 참조 |
| FFmpeg LGPL shared | https://github.com/BtbN/FFmpeg-Builds | 이 빌드는 LGPLv3. 빌드 설정은 `_internal/licenses/ffmpeg-build.txt` |
| Deno | https://github.com/denoland/deno | MIT. 포함된 Rust/V8 의존성의 추가 고지는 공개 배포 전 확인 필요 |
| tzdata | https://github.com/python/tzdata | Apache-2.0 및 IANA 데이터 고지 |
| PyInstaller bootloader | https://pyinstaller.org/ | GPL 및 배포 예외, 수집된 라이선스 참조 |

세부 버전은 `uv.lock` 및 `tools.lock.json`에 고정합니다. 애플리케이션 소스는
https://github.com/blogbooster/WebinarAutoRecorder 를 대상으로 관리합니다.

## 배포 준비 상태

현재 로컬 검증용 빌드입니다. 공개 릴리스 전에는 실제 포함 바이너리에 대응하는 Qt·FFmpeg 등
라이브러리 소스와 빌드 자료의 제공 방식을 확정하고, 배포 아티팩트와 함께 확인해야 합니다.
온라인 소스 링크만으로 모든 배포 의무가 완료되었다고 간주하지 않습니다.
코드 서명 인증서는 아직 구성되지 않았습니다.
