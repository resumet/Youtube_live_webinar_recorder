# YouTube Live Recorder

Windows 10/11에서 허가받은 YouTube 라이브를 자동 감지하고 MP4로 저장하는 프로그램입니다.
원격 저장소 이름은 `WebinarAutoRecorder`이며 제품 이름은 **YouTube Live Recorder**입니다.

현재 **1단계 프로젝트 초기화**를 구현했습니다. 실행 가능한 CLI와 영속 데이터 계층이 있으며,
실제 녹화·자동 감지·GUI·설치 파일은 후속 단계에서 구현합니다. 현재 버전을 녹화용으로 사용하지 마세요.

## 개발 환경 준비

Windows PowerShell에서 프로젝트 폴더를 열고 실행합니다. 최초 준비에는 인터넷과 기존 Python이 필요합니다.
스크립트는 Python 3.13.16과 uv 0.13.1을 프로젝트 내부에 설치합니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
```

`ExecutionPolicy Bypass`는 이 명령으로 시작하는 프로세스에만 적용됩니다. 시스템 정책은 변경하지 않습니다.
의존성은 `pyproject.toml`에 직접 버전을 고정하고, 전이 의존성과 배포 해시는 `uv.lock`에 고정합니다.
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
- 프로세스 시작 전부터 적용되는 DB의 단일 녹화 슬롯 제약.
- 한국어 오류 코드, 로그 순환 저장과 URL·인증 헤더 마스킹.
- 방송/세션 상태 머신과 외부 도구 인터페이스, 네트워크 없는 자동화 테스트.

`add` 명령은 **URL만 저장**하며 메타데이터를 조회하거나 녹화를 시작하지 않습니다.
도움말의 `--permission-confirmed`는 본인이 저장 권한을 확인했음을 뜻합니다.
공개 영상이라는 사실만으로 저장 권한이 생기지는 않습니다.

## 데이터와 로그

`--data-dir`을 생략하면 다음 위치를 사용합니다.

| 항목 | 경로 |
|---|---|
| DB | `%LOCALAPPDATA%\YouTubeLiveRecorder\data\app.db` |
| 로그 | `%LOCALAPPDATA%\YouTubeLiveRecorder\logs\app.log` |
| 기본 녹화 폴더 설정 | `%USERPROFILE%\Videos\YouTubeLiveRecorder` |

개발·테스트에는 `--data-dir .runtime`을 권장합니다. 환경변수 `YLR_DATA_DIR`도 지원하며
명령행 지정이 우선입니다. 녹화 폴더는 현재 설정만 저장하고 생성하지 않습니다.
각 DB 작업은 별도의 연결을 사용하므로 UI와 작업 스레드에서 연결 객체를 공유하지 않습니다.
로그는 파일당 5 MiB, 이전 파일 5개까지 유지합니다. 일부 공개 URL은 DB에 저장되므로
DB나 녹화 파일은 신뢰할 수 있는 사람에게만 공유하세요.

## 문제 해결

- `python`이 없으면 Python을 먼저 설치한 뒤 준비 스크립트를 실행합니다.
- 패키지 다운로드가 막히면 네트워크·프록시 설정을 확인하고 준비 스크립트를 다시 실행합니다.
- 데이터 폴더에 쓰기 권한이 없으면 `--data-dir`로 쓰기 가능한 위치를 지정합니다.
- DB가 더 최신 스키마이면 프로그램은 마이그레이션을 중단하고 데이터를 보존합니다.
- `diagnose`에서 FFmpeg/FFprobe가 없다고 표시되는 것은 1단계에서 예상되는 상태입니다.
  2단계에서 고정 바이너리와 실제 MP4 검사를 연결합니다.
- 최신 yt-dlp는 YouTube 지원을 위해 EJS와 지원되는 JavaScript 런타임을 사용합니다.
  EJS는 잠금 파일에 포함했으며 런타임·FFmpeg 번들은 후속 단계 작업입니다.

## 개발 순서와 검증 범위

1. 초기화, DB, URL/상태 머신 및 단일 슬롯 자동화 테스트.
2. **GUI보다 먼저** yt-dlp/FFmpeg 엔진, 정상 종료·수동 중지·파일 검사 및 로컬 모의 스트림 테스트.
3. 엔진을 호출하는 한국어 PySide6 화면, 트레이, 알림.
4. 재연결·충돌 복구·다시보기·디스크·절전 방지 통합.
5. Windows 실제 방송 검증, PyInstaller one-folder 및 Inno Setup 설치 파일.

수용 기준과 구현 상태는 [구현 계획](docs/IMPLEMENTATION_PLAN.md),
설계 결정과 PRD 보완점은 [설계 기록](docs/DECISIONS.md),
단계별 실행 결과는 [검증 기록](docs/VALIDATION.md)을 확인하세요.
원문은 [PRD](docs/YouTube_Live_Recorder_Codex_PRD.md)입니다.

## 콘텐츠와 외부 구성요소

로그인·브라우저 쿠키 추출·DRM·접근 제한 우회는 제공하지 않습니다.
라이브 처음부터 저장하는 `--live-from-start`는 실험적 기능이며 전체 구간 저장을 보장하지 않습니다.
전체 디코딩 검사는 범위 밖이며 FFprobe 기본 검사를 통과해도 모든 프레임의 정상 재생을 보장하지 않습니다.

공식 근거: [yt-dlp](https://github.com/yt-dlp/yt-dlp),
[EJS/JavaScript 요구사항](https://github.com/yt-dlp/yt-dlp/wiki/EJS).
배포 시 포함할 외부 바이너리의 라이선스·고지는 5단계에서 실제 번들 기준으로 기록합니다.
