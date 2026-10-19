# 설계 결정 및 PRD 보완 기록

## 2026-10-19 · 초기화

- **이름**: 원격 저장소 `WebinarAutoRecorder`를 유지하고 Python 패키지는
  `youtube_live_recorder`, 사용자 표시 이름은 YouTube Live Recorder를 사용한다.
- **Python**: 시스템 Python 3.10.6과 분리해 3.13.16을 사용한다. 프로젝트 내부 uv 관리
  Python과 `.venv`를 사용하고 정확한 버전과 전이 의존성을 고정한다.
- **PRD의 권장 폴더 구조**: `src/app` 대신 충돌 가능성이 낮은 패키지명을 쓴다.
  UI와 녹화 엔진은 분리하고 서비스 계약은 Python Protocol로 정의한다.
- **과거 영상 재등록**: PRD의 미확정 사항은 권장안대로 결정했다. 완료·취소·기한 만료
  항목을 제외한 video ID만 중복 금지한다. 재등록은 새 broadcast UUID로 기록 이력을 보존한다.
- **단일 슬롯**: `CREATED`부터 `VERIFYING`까지 DB 부분 고유 인덱스 `(1)`을 점유한다.
  조회와 생성은 `BEGIN IMMEDIATE` 안에서 처리한다. 완료 파일 검증 없이 슬롯을
  성공으로 해제하지 않는다. 프로세스 단위 앱 잠금/자식 프로세스 수명 관리는 2단계에서 추가한다.
- **마이그레이션**: `PRAGMA user_version`을 사용한다. DDL과 버전 변경을 하나의
  트랜잭션으로 처리한다. 미래 버전 DB를 만나면 중단하며 삭제·자동 다운그레이드하지 않는다.
- **다시보기 만료**: 방송이 아직 끝나지 않았다면 `deadline_at`은 NULL이다.
  종료 추정 시점이 확보되면 UTC 벽시계 기준 24시간을 기록한다. 놓친 시점부터 24시간으로
  계산해 긴 방송을 조기 만료시키지 않는다. 실제 watcher는 4단계에 구현한다.
- **권한**: 등록 시 사용자 확인을 저장한다. 로그인, 쿠키 수집, 접근 제한 우회 기능은 없다.
  URL을 DB에는 보관하되 일부 공개 ID와 서명 URL이 진단 로그에 남지 않도록 URL 전체를 마스킹한다.
- **현재 CLI 범위**: 1단계는 데이터 저장과 초기화 진단만 제공한다. 기본 실행은 도움말이며,
  녹화 서비스가 없는 상태에서 자동 녹화 중인 것처럼 표시하지 않는다.
- **기본 Videos 경로**: 1단계는 홈 폴더의 Videos를 기본 설정으로 제안한다.
  Windows Known Folder(사용자 리디렉션 포함) 경로 조회는 GUI 단계에서 추가해야 한다.
- **사용자 지정 파일명**: 현재는 문자열만 보관하고 파일을 쓰지 않는다.
  실제 출력 직전 파일명 정규화·경로 길이 검사·덮어쓰기 방지를 2단계에서 적용한다.
- **네트워크/도구**: `yt-dlp[default]`를 통해 EJS를 고정 설치한다. 공식 문서상 지원되는
  JavaScript 런타임도 필요하므로 번들에 추가한다. 런타임은 인증/접근 제한 우회에 사용하지 않는다.
- **업데이트**: 존재하지 않는 매니페스트 URL을 만들지 않는다. 현재 설정은 빈 문자열이며
  자동 조회·다운로드·실행은 아직 구현하지 않았다.

근거: [yt-dlp 공식 README](https://github.com/yt-dlp/yt-dlp),
[EJS 공식 설치 안내](https://github.com/yt-dlp/yt-dlp/wiki/EJS).
`--live-from-start`는 실험적이며 성공/전체 구간 보장으로 표시하면 안 된다.

## 2026-10-19 · 녹화 엔진

- **실제 도구 버전**: FFmpeg `n9.0.2-28-g669f5ab083` LGPL shared, Deno `2.9.7`.
  배포 ZIP의 SHA256과 변경되지 않는 릴리스 주소를 `tools.lock.json`에 고정했다.
- **중지 신호**: `CREATE_NO_WINDOW`만 사용하면 콘솔 신호를 전달할 수 없다.
  워커를 `CREATE_NEW_CONSOLE` + `SW_HIDE`로 시작하며 `SetConsoleCtrlHandler(NULL,FALSE)`로
  상속된 Ctrl+C 무시 상태를 해제한다. 별도 신호 helper가 해당 콘솔에만 attach하고
  Ctrl+C를 보내며 짧게 기다린 뒤 detach한다. 실제 Python/FFmpeg 중지 테스트로 검증했다.
- **프로세스 수명**: 워커는 stdin의 시작 메시지 전에 어떤 도구도 실행하지 않는다.
  부모가 KILL_ON_JOB_CLOSE Job Object를 할당한 뒤 시작 메시지를 보내므로, 앱 크래시 후
  녹화 자식만 남는 경쟁 조건을 방지한다. 종료 신호 무시 시 유예 시간 뒤 job 전체를 종료한다.
- **다운로드 격리**: 시스템/사용자 yt-dlp 설정, 외부 플러그인, 원격 EJS 다운로드를
  비활성화한다. EJS와 JavaScript 런타임은 고정 설치본을 사용한다. 로그인·쿠키·DRM 옵션 없음.
- **최종 MP4**: 캡처 파일·분리 영상/음성을 보존하며 복사 remux로 MP4를 만든다.
  코덱 조합이 MP4에 적합하지 않아 remux가 실패하면 성공으로 표시하지 않고 원본을 유지한다.
  자동 전체 재인코딩은 현재 제공하지 않는다.
- **파일 공개 시점**: 이름은 별도 `.reserve` 파일로 예약하고 `.finalizing.mp4` 검사 후
  Windows의 덮어쓰지 않는 rename으로 최종 이름을 공개한다. 기존 파일은 덮어쓰지 않는다.
- **완료 의미**: 두 번의 명시적 방송 종료 응답 + 다운로드 정상 종료 + MP4 기본 검사 통과.
  DVR 전체 구간 보장은 별개이다. 수동 중지는 유효 파일이어도 PARTIAL로 기록하고 방송은
  CANCELLED로 처리해 자동 재시작하지 않는다. 현재 앱 완전 종료에도 같은 정책을 적용한다.
- **경쟁 취소**: 조회 응답이 돌아오기 전에 사용자가 취소한 항목은 상태를 다시 읽고
  건너뛴다. 조회 실패 기록도 종료·취소된 방송을 재활성화할 수 없도록 조건부 갱신한다.
- **단계 경계**: `watch`는 미완료 활성 세션이 있으면 명시적으로 중단한다.
  파일 복구 없이 슬롯을 비우고 중복 녹화를 시작하는 동작은 하지 않는다. 자동 복구는 4단계에 연결한다.

공식 근거: [FFmpeg 배포 안내](https://ffmpeg.org/download.html),
[Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects),
[GenerateConsoleCtrlEvent](https://learn.microsoft.com/en-us/windows/console/generateconsolectrlevent).
