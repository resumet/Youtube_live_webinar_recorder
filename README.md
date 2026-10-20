# YouTube Live Recorder

Windows 10/11에서 허가받은 YouTube 라이브를 자동 감지하고 MP4로 저장하는 프로그램입니다.
원격 저장소 이름은 `WebinarAutoRecorder`이며 제품 이름은 **YouTube Live Recorder**입니다.

한국어 GUI에서 자동 감지·녹화·수동 중지, 재연결·충돌 후 파일 복구·다시보기 저장과
기록 확인을 실행할 수 있습니다. Python 없이 실행하는 Windows 폴더형 빌드와
승인형 업데이트 기능과 **v0.2.0의 여러 라이브 동시 녹화**를 제공합니다.
**v0.3.0**은 왼쪽 메뉴의 **종료영상 다운로드**에서 종료된 라이브의 전체 다시보기를 저장합니다.
**v0.2.1**은 진행 중인 녹화 섹션에 **저장 폴더 열기**와 **구글 드라이브 열기**를 추가합니다.
저장 폴더 버튼은 선택한 녹화의 실제 저장 위치를 열고, 녹화가 없으면 설정된 저장 폴더를 엽니다.
구글 드라이브 버튼은 지정된 폴더 링크를 기본 브라우저로 엽니다.
기본 동시 녹화 수는 **5개**이며 설정에서 1~10개로 변경할 수 있습니다.
v0.1.0에서는 Windows 11 설치·재설치·제거와 데이터 보존, 실제 경과 3시간의 단일 로컬
스트림 시험을 통과했습니다. v0.2.0은 복수 녹화에 대한 별도 검증 결과를 기록합니다.
v0.3.0 자동화 테스트 **191개**를 통과했습니다. 새 Windows 번들로 5개 동시 저장,
종료영상 전체 다운로드의 원본 길이 일치, FFprobe·DB 검사와 GUI 실행을 확인했습니다.
100/125/150/200% 배율의 다섯 화면 검사도 통과했습니다. 현재 PC의 기존 설치본을 보호하기 위해
v0.2 이후 설치·재설치·제거 시험은 실행하지 않았습니다.
실행 증거는 [검증 기록](docs/VALIDATION.md), 미확인 항목은 [수용 기준 점검표](docs/ACCEPTANCE.md)를 확인하세요.
실제 Windows 트레이·알림을 확인하는 방법은 [수동 확인 안내](docs/MANUAL_TESTS.md)에 있습니다.

## 빌드된 프로그램 실행

설치하려면 다음 파일을 실행하고 설치 후 시작 메뉴에서 **YouTube Live Recorder**를 엽니다.
기존 앱을 사용 중이면 녹화를 마친 뒤 **완전 종료**하고 업데이트하세요.
설치 파일의 SHA256은 같은 폴더의 `.exe.sha256` 파일과 대조할 수 있습니다.

```powershell
.\dist\installer\YouTubeLiveRecorder-0.3.0-Setup.exe
```

설치 없이 폴더형 프로그램으로 실행할 수도 있습니다.
`dist/YouTubeLiveRecorder/` 폴더 전체를 유지한 채 `YouTubeLiveRecorder.exe`를 실행합니다.
`_internal`과 `YouTubeLiveRecorderWorker.exe`도 함께 필요합니다. 이 빌드는 FFmpeg/FFprobe,
Deno, Python, Qt를 포함합니다. 개발용 Python이나 별도 FFmpeg 설치는 필요하지 않습니다.

```powershell
.\dist\YouTubeLiveRecorder\YouTubeLiveRecorder.exe
```

최초 실행 후 설정에서 저장 폴더를 확인하고, 대시보드에 허가받은 URL과 화질을 등록하세요.
**설정 → 녹화 저장 위치 → 폴더 선택**으로 저장소를 변경할 수 있습니다.
변경한 폴더는 이후 시작하는 녹화부터 적용되며 진행 중인 녹화와 기존 파일은 원래 위치에 유지됩니다.
**설정 → 동시 녹화**에서 상한을 저장합니다. 상한을 낮춰도 진행 중인 녹화는 계속됩니다.
대시보드의 진행 목록에서 방송을 선택하고 **선택한 녹화 중지**를 누르면 해당 방송만 중지합니다.
상한을 초과한 방송은 등록 순서대로 60초마다 다시 확인하며, 대기 중 종료되면 다시보기를 확인합니다.
앱을 완전히 종료하면 감지도 중단됩니다. 다음 실행 시 목록과 설정을 복원하고 다시 감지합니다.

종료된 방송은 **종료영상 다운로드**에서 URL, 화질, 선택 파일명과 저장 권한을 확인한 뒤
**전체 영상 다운로드**를 누르세요. 라이브 URL의 시간 위치와 무관하게 YouTube에서 제공하는
전체 다시보기를 MP4로 저장합니다. 처리 중인 다시보기는 60초마다 확인하고, 동시 처리 상한에
도달하면 기다렸다가 시작합니다. 오래전에 종료된 영상에도 자동 다시보기의 24시간 만료를 적용하지 않습니다.
목록에서 상태·받은 데이터 확인, 선택 작업 중지·취소·오류 재시도와 실제 저장 폴더 열기가 가능합니다.
완료 파일은 녹화 기록에도 남습니다. 재시작 시 미완료 다운로드는 부분 파일을 보존하고 처음부터 다시 시도합니다.
YouTube가 제공하지 않는 원방송 구간을 복원하거나 접근 제한을 우회하지 않습니다.

## 개발 환경 준비

Windows PowerShell에서 프로젝트 폴더를 열고 실행합니다. 최초 준비에는 인터넷과 기존 Python이 필요합니다.
스크립트는 Python 3.13.16과 uv 0.13.1을 프로젝트 내부에 설치합니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
.\.venv\Scripts\python.exe scripts/fetch_tools.py
```

`ExecutionPolicy Bypass`는 이 명령으로 시작하는 프로세스에만 적용됩니다. 시스템 정책은 변경하지 않습니다.
의존성은 `pyproject.toml`에 직접 버전을 고정하고, 전이 의존성과 배포 해시는 `uv.lock`에 고정합니다.
`fetch_tools.py`는 `tools.lock.json`에 고정한 FFmpeg/FFprobe와 Deno를 SHA256 검증 후
`.tools/`에 설치합니다. FFmpeg는 LGPL shared 빌드를 사용하며 전체 DLL 디렉터리를 유지해야 합니다.
가상환경 활성화 없이 다음 명령을 사용할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe -m youtube_live_recorder --data-dir .runtime init
.\.venv\Scripts\python.exe -m youtube_live_recorder --data-dir .runtime diagnose
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests
```

실행 도구의 도움말:

```powershell
.\.venv\Scripts\python.exe -m youtube_live_recorder --help
```

## 현재 사용할 수 있는 기능

- `watch?v=`, `/live/`, `youtu.be/` URL 검증과 동일 영상 ID 정규화.
- 녹화 권한 확인을 전제로 대기 목록 등록, 목록 조회, 대기 취소.
- SQLite WAL, 외래키, 트랜잭션, 버전 관리 마이그레이션.
- 재실행 시 대기 목록·설정 유지, 활성 항목 중복 차단.
- 프로세스 시작 전부터 적용되는 DB의 동시 녹화 상한과 방송별 중복 녹화 차단.
- 한국어 오류 코드, 로그 순환 저장과 URL·인증 헤더 마스킹.
- 방송/세션 상태 머신과 외부 도구 인터페이스, 네트워크 없는 자동화 테스트.
- 60초 간격 자동 감지, 등록 순 우선권, 상한 초과 방송의 지속적인 라이브 확인.
- 720p/1080p/최고 화질 상한 선택, 가용한 낮은 화질 선택과 실제 해상도 기록.
- 실험적 DVR 처음부터 저장 시도, 해당 형식의 미지원 시 현재 시점 폴백.
- Windows 숨겨진 콘솔의 정상 중지, Job Object를 통한 자식 프로세스 수명 관리.
- 영상·음성을 MP4로 정리하고 FFprobe 검사 후 완료 또는 부분 기록.

## 엔진 실행

```powershell
.\.venv\Scripts\python.exe -m youtube_live_recorder --data-dir .runtime inspect "허가받은 YouTube URL"
.\.venv\Scripts\python.exe -m youtube_live_recorder --data-dir .runtime add "허가받은 YouTube URL" --permission-confirmed --quality 720p
.\.venv\Scripts\python.exe -m youtube_live_recorder --data-dir .runtime watch
```

`watch`를 실행한 터미널에서 Ctrl+C를 누르면 진행 중인 파일을 정리하고 부분 녹화로 기록합니다.
프로그램 완전 종료나 Ctrl+C로 중단한 방송은 다음 실행에서 상태를 재확인합니다.
GUI의 **녹화 중지**로 취소한 방송은 다음 실행에서 자동으로 다시 녹화하지 않습니다.
정상 완료는 파일 검사와 방송 종료 상태 재확인 후 기록합니다. 시작 구간 완전성은 보장하지 않습니다.

한국어 데스크톱 화면은 다음 명령으로 실행합니다. 설정 화면에서 저장 폴더를 선택할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe -m youtube_live_recorder --data-dir .runtime gui
```

방송 정보를 미리 조회하거나 URL만 등록할 수 있습니다. 창의 닫기/최소화는 트레이로 숨기며,
왼쪽 아래 또는 트레이 메뉴의 **완전 종료**가 감지를 중단하고 진행 파일을 정리합니다.
트레이를 사용할 수 없는 환경에서는 창을 닫을 때 완전 종료 여부를 확인합니다.
임시 산출물은 녹화 폴더의 `.ylr-work/<세션 UUID>/`에 보존하며 자동 삭제하지 않습니다.
미완료 세션이 남으면 먼저 임시 파일을 검사·복구하고 슬롯을 해제한 뒤 방송 상태를 재확인합니다.
진행 중인 방송은 새 구간으로 재개하며 원래 파일은 보존합니다. 복구 파일은 부분 저장으로 기록합니다.

## 장애 복구와 다시보기

- 연결이 끊기면 15초부터 지수 백오프와 jitter로 최대 6회 재연결합니다. 재개 파일은
  `_구간02.mp4`처럼 따로 저장합니다. 구간을 임의로 이어 붙이거나 누락을 정상 완료로 표시하지 않습니다.
- 라이브 재시도 한도를 넘으면 다시보기 큐로 전환합니다. 종료를 처음 관찰한 시각부터
  24시간 동안 30분 간격으로 확인하며, 기한은 재시작·수동 재시도에도 연장되지 않습니다.
- 공개된 허용 다시보기는 별도 `_다시보기.mp4` 파일로 저장합니다. 라이브가 시작되면 진행 중인
  다시보기를 정리하고 대기 상태로 돌립니다. 추후 다시보기는 처음부터 새 파일로 다운로드합니다.
- 녹화 전과 진행 중 5초 간격으로 저장소를 확인합니다. 기본 여유 공간 기준은 1 GiB이며,
  MP4 정리 전에는 원본을 유지한 채 새 파일을 만들 공간도 확인합니다. 공간/장치를 복구한 뒤
  대기 목록의 **오류 다시 확인**을 사용할 수 있습니다.
- 대기·녹화·복구 중 Windows 자동 절전을 방지합니다. 모니터 꺼짐은 허용하며 완전 종료 시 해제합니다.
- 기록의 길이·용량은 같은 세션의 저장된 구간 합계입니다. 여러 파일인 경우 안내 열에 표시하며
  **폴더 열기**로 모든 구간을 확인할 수 있습니다. 최종 파일이 없는 실패 기록은 임시 작업 폴더를 엽니다.
- FFprobe로 복구할 수 없는 조각도 삭제하지 않습니다. 앱을 다시 실행할 때 실패한 파일을 다시 검사합니다.
  복구 직후 다시 앱이 강제 종료되면 동일 내용의 추가 복구 파일이 생길 수 있으나 기존 파일을 덮어쓰지 않습니다.

## 업데이트와 설치 파일 빌드

업데이트 배포 주소는 기본값이 비어 있습니다. 실제 배포용 HTTPS 매니페스트를
`YLR_UPDATE_MANIFEST_URL` 또는 DB 설정 `update_manifest_url`로 지정한 경우 새 버전을 확인합니다.
다운로드와 설치는 각각 사용자 동작이 필요하며, SHA256 검증과 설치 직전 재검사를 수행합니다.
녹화·복구·파일 정리 중에는 설치하지 않습니다. 실제 배포 서버나 서명 인증서는 아직 구성하지 않았습니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/fetch_inno.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build.ps1
```

첫 명령은 공식 해시와 게시자 서명을 확인한 Inno Setup을 프로젝트 내부에 준비합니다.
두 번째 명령은 테스트 → PyInstaller → 번들 실행 검사 → 설치 파일 생성을 수행합니다.
컴파일러 준비에 실패하면 Setup.exe를 생성한 것으로 처리하지 않습니다.
출력 경로와 설치·제거 검증 절차는 [패키징 안내](docs/PACKAGING.md)에 있습니다.

`add` 명령은 **URL만 저장**하며 `inspect`는 정보 조회, `watch`는 조회·자동 감지·녹화를 담당합니다.
도움말의 `--permission-confirmed`는 본인이 저장 권한을 확인했음을 뜻합니다.
공개 영상이라는 사실만으로 저장 권한이 생기지는 않습니다.

## 데이터와 로그

`--data-dir`을 생략하면 다음 위치를 사용합니다.

| 항목 | 경로 |
|---|---|
| DB | `%LOCALAPPDATA%\YouTubeLiveRecorder\data\app.db` |
| 로그 | `%LOCALAPPDATA%\YouTubeLiveRecorder\logs\app.log` |
| 기본 녹화 폴더 설정 | Windows 동영상 폴더 아래 `YouTubeLiveRecorder` (이동된 동영상 폴더 지원) |

개발·테스트에는 `--data-dir .runtime`을 권장합니다. 환경변수 `YLR_DATA_DIR`도 지원하며
명령행 지정이 우선입니다. 녹화 폴더는 녹화 시작 시 생성하며 여유 공간과 쓰기 권한을 검사합니다.
각 DB 작업은 별도의 연결을 사용하므로 UI와 작업 스레드에서 연결 객체를 공유하지 않습니다.
로그는 파일당 5 MiB, 이전 파일 5개까지 유지합니다. 일부 공개 URL은 DB에 저장되므로
DB나 녹화 파일은 신뢰할 수 있는 사람에게만 공유하세요.

## 문제 해결

- `python`이 없으면 Python을 먼저 설치한 뒤 준비 스크립트를 실행합니다.
- 패키지 다운로드가 막히면 네트워크·프록시 설정을 확인하고 준비 스크립트를 다시 실행합니다.
- 데이터 폴더에 쓰기 권한이 없으면 `--data-dir`로 쓰기 가능한 위치를 지정합니다.
- DB가 더 최신 스키마이면 프로그램은 마이그레이션을 중단하고 데이터를 보존합니다.
- `diagnose`에서 FFmpeg/FFprobe가 없다고 표시되면 `scripts/fetch_tools.py`를 실행합니다.
- 최신 yt-dlp는 YouTube 지원을 위해 EJS와 지원되는 JavaScript 런타임을 사용합니다.
  EJS는 잠금 파일에 포함했으며 Deno와 FFmpeg도 별도 잠금 파일로 고정했습니다.

## 개발 순서와 검증 범위

1. 초기화, DB, URL/상태 머신 및 단일 슬롯 자동화 테스트.
2. **GUI보다 먼저** yt-dlp/FFmpeg 엔진, 정상 종료·수동 중지·파일 검사 및 로컬 모의 스트림 테스트.
3. 엔진을 호출하는 한국어 PySide6 화면, 트레이, 알림.
4. 재연결·충돌 복구·다시보기·디스크·절전 방지 통합.
5. Windows 실제 방송 검증, PyInstaller one-folder 및 Inno Setup 설치 파일.

수용 기준과 구현 상태는 [구현 계획](docs/IMPLEMENTATION_PLAN.md),
현재 수용 기준별 검증 범위는 [수용 기준 점검표](docs/ACCEPTANCE.md),
설계 결정과 PRD 보완점은 [설계 기록](docs/DECISIONS.md),
단계별 실행 결과는 [검증 기록](docs/VALIDATION.md)을 확인하세요.
원문은 [PRD](docs/YouTube_Live_Recorder_Codex_PRD.md)입니다.

## 콘텐츠와 외부 구성요소

로그인·브라우저 쿠키 추출·DRM·접근 제한 우회는 제공하지 않습니다.
라이브 처음부터 저장하는 `--live-from-start`는 실험적 기능이며 전체 구간 저장을 보장하지 않습니다.
전체 디코딩 검사는 범위 밖이며 FFprobe 기본 검사를 통과해도 모든 프레임의 정상 재생을 보장하지 않습니다.

공식 근거: [yt-dlp](https://github.com/yt-dlp/yt-dlp),
[EJS/JavaScript 요구사항](https://github.com/yt-dlp/yt-dlp/wiki/EJS).
실제 번들 기준 라이선스·고지 및 공개 배포 전 남은 사항은 [외부 구성요소 고지](docs/THIRD_PARTY.md)에 있습니다.
