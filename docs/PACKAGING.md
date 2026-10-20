# Windows 빌드와 검증

작업 폴더에서 `scripts/bootstrap.ps1`과 `scripts/fetch_tools.py`로 고정 의존성을 준비한다.
PyInstaller는 `uv.lock`의 build 그룹에 포함되어 있다. 설치 파일은 Windows x64용이다.
Qt 6.12의 지원 범위에 맞춰 Windows 10 1809(빌드 17763) 이상 또는 Windows 11을 대상으로 한다.
현재 실제 실행 환경은 Windows 11이며 Windows 10 검증은 별도로 남아 있다.
근거: [Qt 지원 플랫폼](https://doc.qt.io/qt-6/supported-platforms.html).

## 빌드

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/fetch_inno.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build.ps1
```

Inno Setup 7.1.0 x64의 고정 릴리스를 SHA256과 Authenticode 게시자 `Pyrsys B.V.`로 검증한다.
컴파일러는 `.tools/inno`에 portable 모드로 준비하며 전역 설치를 요구하지 않는다.
네트워크·승인 오류로 준비되지 않으면 빌드는 설치 단계에서 명시적으로 실패한다.

빌드 순서: Ruff → pytest → 도구/고지 수집 → PyInstaller → 번들 실행 검사 → Inno Setup.
검사 통과 전에 설치 파일을 성공 산출물로 보고하지 않는다.

| 산출물 | 경로 |
|---|---|
| 폴더형 실행 파일 | `dist/YouTubeLiveRecorder/YouTubeLiveRecorder.exe` |
| 콘솔 진단/녹화 워커 | `dist/YouTubeLiveRecorder/YouTubeLiveRecorderWorker.exe` |
| 공유 라이브러리·도구·고지 | `dist/YouTubeLiveRecorder/_internal/` |
| 설치 파일 (컴파일 성공 시) | `dist/installer/YouTubeLiveRecorder-0.3.1-Setup.exe` |

GUI 실행 파일 하나만 복사하면 동작하지 않는다. 폴더 전체를 복사하거나 설치 파일을 사용한다.
작업 공간의 DB·녹화·로그·테스트 URL은 패키지에 포함하지 않는다.

## 실행 파일 검증

```powershell
.\.venv\Scripts\python.exe scripts/verify_package.py
.\.venv\Scripts\python.exe scripts/verify_package.py --qt-platform windows
.\dist\YouTubeLiveRecorder\YouTubeLiveRecorderWorker.exe --data-dir .runtime\manual-diagnostic diagnose
.\dist\YouTubeLiveRecorder\YouTubeLiveRecorderWorker.exe --data-dir .runtime\manual-diagnostic self-test
```

`verify_package.py`는 시스템 PATH의 Python/FFmpeg/Deno와 `PYTHONPATH`를 제외한 환경에서
번들 진단, 실제 yt-dlp 5개 작업의 로컬 미디어 동시 다운로드/MP4 검사,
종료영상 전체 다운로드의 원본 길이 일치, GUI 렌더링·응답·정상 종료를 확인한다.
호출에 사용한 개발 Python은 검사 진행만 담당한다. 결과와 화면은 `.runtime/package-tests/`에 남는다.
Qt offscreen 검사와 실제 Windows 트레이/알림 센터 클릭 검증은 별개이다.
`--qt-platform windows`는 실제 qwindows 플러그인에서도 같은 검사를 수행한다.
외부 방송 없이 트레이/알림 클릭을 직접 확인하는 절차는 [Windows 수동 확인](MANUAL_TESTS.md)에 있다.

화면 크기와 배율 회귀는 다음 명령으로 확인한다.

```powershell
.\.venv\Scripts\python.exe scripts/verify_display.py
```

이 검사는 실제 번들을 각각 새 데이터 폴더에서 실행하고 Qt 배율 1/1.25/1.5/2를 적용한다.
종료영상 다운로드를 포함한 다섯 페이지를 렌더링하고, 가용 화면 안에 창이 들어오는지 확인한다.
Windows의 전역 화면 설정은 변경하지 않는다. `QT_SCALE_FACTOR`는 실제 장치 배율에 곱해지므로
결과에는 요청값과 관찰된 장치 배율을 함께 기록한다. 물리적인 다중 모니터 이동·핫플러그 시험과는 다르다.
근거: [Qt High DPI 테스트](https://doc.qt.io/qt-6/highdpi.html#testing).

## 장시간 검증

빈 개발 전용 데이터 폴더를 지정해야 한다. 다음은 실제 3시간이 걸리며 YouTube에는 접속하지 않는다.
시험 중 `.runtime/soak-3h/result.json`이 1분 간격으로 갱신된다.

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\dist\YouTubeLiveRecorder\YouTubeLiveRecorderWorker.exe --data-dir .runtime\soak-3h soak-test --seconds 10800 --report .runtime\soak-3h\result.json
```

FFmpeg가 실시간으로 자체 영상을 생성한다. 실제 엔진의 한 녹화 작업·디스크 감시·GUI·전원 API와
MP4 마무리·FFprobe·DB 완료 경로를 사용한다. 성공하려면 3시간 경과, 검사 통과,
정상 종료 및 UI 타이머 간격 5초 미만을 모두 만족해야 한다. 짧은 시험은 3시간 검증을 대신하지 않는다.
이 명령은 한 영상만 사용하므로 복수 녹화의 장시간 시험을 대신하지 않는다.

## 설치·업데이트·제거 검증

설치 파일이 생성된 후 다음을 실제 Windows에서 확인하고 결과를 `VALIDATION.md`에 기록한다.

```powershell
.\.venv\Scripts\python.exe scripts/verify_installer.py --running-guard-only
# 장시간 시험과 앱을 완전히 종료한 뒤:
.\.venv\Scripts\python.exe scripts/verify_installer.py
```

두 명령 모두 기존 제품 설치가 없는 환경에서만 실행한다. 첫 명령은 폴더형 앱 실행 중 설치가
차단되는지만 확인한다. 두 번째 명령은 앱도 실행 중이지 않을 때
작업 폴더 아래 별도 경로에 설치·재설치·제거하고, 설치본 실행 및 별도 사용자 DB/파일 보존을 검사한다.
일반 사용자 설치 등록 및 고유한 시작 메뉴 폴더를 생성하므로 환경의 승인 절차가 필요한 경우 이를 따른다.
실패 시 시험 로그와 설치 경로를 보존한다. 기존 설치를 발견하면 덮어쓰거나 제거하지 않는다.
자동 검증용 DB 경로는 `--data-dir`로 분리하며 실제 사용자의 기본 DB를 수정하지 않는다.

1. 관리자 권한 없이 설치, 시작 메뉴 및 선택한 바탕 화면 바로가기로 실행.
2. URL 대기 목록·설정 저장 후 완전 종료, 재실행하여 복원.
3. 실행 중인 앱이 있을 때 설치/제거가 파일을 교체하지 않는지 확인.
4. 재설치 후 DB·설정·별도 폴더의 녹화 파일 유지.
5. 제거 후 앱 바이너리만 제거되고 DB·로그·녹화 파일이 유지되는지 확인.

이 설치 스크립트는 사용자 데이터를 삭제하지 않는다. 제거 후 직접 보관/정리할 위치는
`%LOCALAPPDATA%/YouTubeLiveRecorder`와 사용자가 선택한 녹화 폴더이다.

## 업데이트 배포 설정

실제 HTTPS 매니페스트 주소를 `YLR_UPDATE_MANIFEST_URL` 또는 DB의 `update_manifest_url`로 지정한다.
기본 주소는 비어 있으며 존재하지 않는 릴리스를 조회하지 않는다. 매니페스트 필드는 다음과 같다.

| 필드 | 형식 |
|---|---|
| `version` | `0.1.1`과 같은 세 정수 버전 |
| `download_url` | 실제 설치 파일의 HTTPS URL |
| `sha256` | 해당 설치 파일의 64자리 SHA256 |
| `notes` | 한국어 변경 내용 문자열 (선택) |

새 버전 확인 → 사용자 다운로드 → SHA256 검사 → 사용자 설치 확인 → 유휴 상태 확인 →
앱 안전 종료 → 설치 프로그램 실행 순서다. 녹화 중에는 설치하지 않는다. 실제 서버를 통한
다운로드/업데이트 및 코드 서명은 현재 미검증이며 로컬 모의 응답 테스트 결과와 구분한다.

공개 배포 전 구성요소 고지·대응 소스 확인 사항은 [THIRD_PARTY.md](THIRD_PARTY.md)를 따른다.
