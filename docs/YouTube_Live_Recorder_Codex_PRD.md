# YouTube Live Recorder — Windows 데스크톱 앱 상세 PRD

- 문서 버전: 1.0
- 작성일: 2026-10-19
- 개발 대상: Codex / Python 개발자
- 상태: 사용자 41개 질문 중 1~40번 기능 의사결정 및 41번 문서 수준(상세 PRD) 반영
- 운영 범위: 단일 사용자, Windows 10/11, 한국어

## 1. 프로젝트 개요
유튜브 공개 및 일부 공개 라이브 웨비나 URL을 등록하면, 앱이 60초마다 방송 시작 여부를 감지하여 최대 1개 방송을 자동 녹화하고, 종료 시 오디오가 포함된 MP4로 안전하게 저장하는 개인용 Windows 설치형 프로그램을 개발한다. 프로그램 UI를 닫아도 시스템 트레이에서 동작한다. 놓친 방송은 허용된 다시보기가 제공될 때 최대 24시간 동안 확인해 다운로드를 시도한다.

### 1.1 핵심 성공 기준
- 별도 시작 시각 설정 없이 예정된 방송 URL만 등록하면 감지 및 녹화 시작.
- 프로그램 재실행 후 대기 목록과 설정이 복원되고 감지 재개.
- 최대 1개 동시 녹화 보장, 오류/재연결/복구 중에도 중복 프로세스 방지.
- 정상 종료 후 FFprobe 기본 검사 통과 시 MP4 완료 처리.
- 클릭 가능한 완료 알림으로 파일 폴더 열기.

### 1.2 범위 제외
- 채널 전체 모니터링, 동시에 여러 방송 녹화, 로그인·쿠키 추출·회원 전용 방송, DRM/접근 제한 우회, 자동 Windows 시작 실행, 개인 계정, 클라우드 동기화, PC 자동 종료, 영상 미리보기, MP3 별도 저장, 원본 전체 디코딩 검사, 자동 무인 업데이트, 다운로드 우회 기능.

### 1.3 법적/운영 제약
본인이 녹화 및 저장 권한을 가진 스트림만 사용. 공개/일부 공개라는 사실 자체는 복제·재배포 허락을 의미하지 않는다. 접근 제한, DRM, 인증 보호 및 서비스 정책을 우회하지 않는다. 해당 스트림/다시보기에서 다운로드가 허용되는 경우에만 수행하며, 실패를 성공으로 표시하지 않는다.

## 2. 확정 요구사항 (FR)

| ID | 요구사항 | 우선순위 |
|---|---|---|
| FR-01 | YouTube `watch?v=`, `/live/`, `youtu.be/` 형태 URL에서 video ID 파싱 및 검증 | P0 |
| FR-02 | 동일 video ID 대기/진행 목록 중복 등록 차단 | P0 |
| FR-03 | URL 등록 시 제목, 채널명, 썸네일, 예정 시작 시각(제공 시), 방송 상태 조회; 조회 실패 시 URL만 등록 가능 | P0 |
| FR-04 | 여러 URL 대기 목록 등록/수정/취소 및 재실행 복원 | P0 |
| FR-05 | 60초마다 라이브 상태 확인; 오류/레이트 리밋은 지수 백오프 및 jitter 적용 | P0 |
| FR-06 | 최초 감지되어 녹화 슬롯을 획득한 방송 1개만 녹화; 동시 시작 시 등록 시각 빠른 항목 우선 | P0 |
| FR-07 | 다른 방송이 이미 진행 중이면 신규 라이브는 건너뛰고 명시적 `MISSED_BUSY` 처리; 후속 다시보기 복구 대상 | P0 |
| FR-08 | 720p, 1080p, 최고 화질 선택; 불가 시 낮은 사용 가능 화질로 폴백 및 실제 화질 기록 | P0 |
| FR-09 | 영상과 음성을 결합한 MP4 생성; 다운로드 중 임시 산출물을 완료 파일과 구분 | P0 |
| FR-10 | 감지 직후 DVR 허용 시 방송 시작 지점부터 시도, 실패 시 라이브 에지에서 시작; 구간 완전성 보장 금지 | P1 |
| FR-11 | 방송 종료 감지·저장 완료 후 FFprobe로 영상/음성 스트림, 길이, 컨테이너 검증 | P0 |
| FR-12 | 녹화 중 수동 중지 시 FFmpeg/yt-dlp 정상 종료 요청 → 파일 마무리 → 검사 → 기록 | P0 |
| FR-13 | 녹화 실패/일시적 인터넷 끊김 시 재연결, 이전 파일 보존, 재개 구간은 별도 세그먼트 허용 | P0 |
| FR-14 | 앱/PC 충돌 후 실행 시 미완료 작업 검사, 임시 파일 복구 시도, 계속 방송 중이면 녹화 재개 | P0 |
| FR-15 | 실패·앞부분 누락·건너뜀에 대해 종료 이후 공개된 허용 다시보기 30분 주기로 최대 24시간 확인/다운로드 | P0 |
| FR-16 | 이미 저장한 실시간 녹화 파일은 다시보기 다운로드 시에도 유지; 전체 다시보기는 별도 파일 | P0 |
| FR-17 | 사용자가 저장 폴더 선택; 외장 드라이브 사용 가능. 비가용 경로 알림 | P0 |
| FR-18 | `YYYY-MM-DD_방송제목.mp4` 기본 이름: 실제 방송 시작일(Asia/Seoul), 사용자 지정 이름 우선 | P0 |
| FR-19 | 파일명에서 Windows 금지 문자/예약 이름/너무 긴 길이 정규화; 충돌 시 `(2)` 등 접미사 | P0 |
| FR-20 | 대시보드/녹화 대기/녹화 기록/설정 메뉴의 한국어 UI | P0 |
| FR-21 | 현재 녹화 상태, 진행 시간, 저장 파일 용량, 실제 화질, 저장 경로 실시간 표시 | P0 |
| FR-22 | 기록에 제목/날짜/길이/용량/성공 여부/파일·폴더 열기 표시; 검색/삭제 기능 제외 | P0 |
| FR-23 | 완료 시 대기 → 녹화 기록으로 이동; 오류 및 다시보기 대기 상태는 대기 목록에 보존 | P0 |
| FR-24 | 최소화·창 X는 트레이로 숨김, 종료 메뉴는 확인창 표시; 녹화 시 안전한 종료 | P0 |
| FR-25 | 트레이 색상: 녹색 대기, 빨간색 녹화, 노란색 오류; hover 시 상태·진행 시간 | P1 |
| FR-26 | 녹화 시작/완료 Windows 알림; 완료 알림 클릭 시 탐색기로 해당 파일 폴더 열기 | P0 |
| FR-27 | 저장소 디스크 여유 공간을 녹화 전 및 중간에 검사; 부족 시 경고·데이터 최대 보존 | P0 |
| FR-28 | 방송 대기 및 녹화 중 자동 절전 방지, 모니터 꺼짐 허용, 완전 종료 시 해제 | P0 |
| FR-29 | 새 릴리스 감지 시 업데이트 알림·사용자 승인 후 설치; 녹화 중 설치 불허 | P1 |
| FR-30 | 진단 가능한 오류 분류 및 한국어 해결 안내 | P0 |
| FR-31 | 다운로드/녹화 완료 이후 PC 자동 종료 없음 | P0 |
| FR-32 | 앱 재시작 시 기존 대기 항목의 상태를 재검증하고 감지 자동 재개 | P0 |

## 3. 사용자 흐름
1. 최초 실행 → 저장 위치 기본값(Windows Videos 하위 폴더) 제안 → 사용자 변경 가능.
2. URL 입력 → 유효성 검사 및 video ID 추출 → 메타데이터 조회 → 썸네일/제목/채널/예정 시간 표시.
3. 화질 선택, 기본 파일명 또는 수동 수정 → 등록 → SQLite 커밋 → 대기 목록 표시.
4. 대기 모니터 60초마다 체크 → 방송 시작 시 단일 슬롯 획득 → 녹화 세션 생성 → 절전 방지 및 시작 알림.
5. 녹화 UI에서 경과 시간/파일 크기/화질/상태 확인 → 방송 종료 시 마무리/검사 → MP4 기록·알림.
6. 사용자 수동 종료: 확인창 → 정상 종료 요청 → 파일 정리·검사 → 앱 종료.
7. 실패/누락 감지 시 24시간 내 허용된 다시보기 체크 → 다운로드 시도 → 별도 파일로 보관.

## 4. 화면 세부 명세

### 4.1 대시보드
- 상단: 상태 요약(모니터링 중, 녹화 중, 오류, 대기 수), 네트워크/디스크 상태.
- 중앙: URL 입력, 메타데이터 미리보기, 화질 선택, 파일명 변경, 등록 버튼.
- 하단: 최근 항목 및 진행 중인 녹화(경과 시간/크기/실제 화질/경로/중지 버튼).
- 빈 상태/조회 실패/권한 문제를 한국어로 구분.

### 4.2 녹화 대기
- 컬럼: 제목, 채널, 영상 ID, 예정 시작, 상태, 화질, 파일명, 등록 시각.
- 기능: 등록 항목 수정, 취소; 완료 항목 자동 제외; 오류/다시보기 대기는 상태로 표시.
- 우선순위: 시작이 감지된 방송 중 등록 시각이 빠른 항목.

### 4.3 녹화 기록
- 컬럼: 시작 날짜, 제목, 원본 URL, 결과(성공/부분/실패), 길이, 크기, 경로.
- 클릭: 파일 열기, 탐색기에서 폴더 열기; 파일을 삭제하거나 검색·필터하는 기능은 제공하지 않음.

### 4.4 설정
- 저장 폴더 선택, 앱 버전/업데이트 확인, 장치/저장 오류 메시지.
- 라이브 확인 주기는 60초 고정, 다시보기 확인 주기는 30분 고정.
- 한국어 고정, Windows 자동 시작 옵션 없음.

## 5. 기술 아키텍처

### 5.1 스택
- Python (지원되는 안정 버전 고정), PySide6, yt-dlp(최신 호환 버전 고정), FFmpeg/FFprobe, SQLite, PyInstaller, Inno Setup.
- Windows API: `SetThreadExecutionState`로 자동 절전만 방지; 앱 종료/일시 정지 시 해제.
- QSystemTrayIcon으로 상태/알림 처리. Windows 환경에서 알림 클릭 동작 검증 필요.

### 5.2 권장 모듈
```
src/
  main.py
  app/ui/{main_window,dashboard,queue,history,settings,dialogs}.py
  app/core/{scheduler,live_detector,recording_manager,recovery_manager,playback_watcher,metadata}.py
  app/services/{ytdlp_adapter,ffmpeg_adapter,ffprobe_adapter,power_manager,notification,update_checker}.py
  app/data/{db,models,repository,migrations}.py
  app/utils/{urls,filenames,errors,logging,paths}.py
assets/{icons,translations}/
packaging/{pyinstaller.spec,installer.iss}/
tests/{unit,integration,fixtures}/
```
- 메인 UI 스레드에서 네트워크·yt-dlp·FFmpeg 동기 작업 금지. 작업 스레드/프로세스를 시그널로 연결.
- yt-dlp는 subprocess로 실행하고 argv 목록 사용; 셸 명령 문자열 연결 금지. stderr/stdout 별도 로그 캡처 및 파싱.
- 가능하면 외부 도구 버전/경로를 시작 시 검증하고 의존 바이너리를 앱 패키지에 포함. FFmpeg 라이선스 고지 포함.
- yt-dlp 추출 결과/출력 형태는 버전에 따라 변할 수 있으므로 어댑터로 감싼다.

### 5.3 단일 녹화 제어
- `RecordingManager`에서 프로세스 단위 mutex/lock 보유.
- `start_recording(video_id)`는 트랜잭션에서 활성 세션 유무 확인, 상태 전이, 독점 슬롯 획득 후 프로세스 시작.
- 크래시로 락이 풀린 경우 재기동 시 DB `RECORDING` 상태를 회복 작업으로 전환.
- 유튜브 생방송은 일시적 스트림 오류와 실제 종료가 구분 어려움. 단일 HTTP 오류만으로 방송 종료 판단 금지; 재조회/종료 확인 사용.
- `--live-from-start`는 실험적 기능이므로 우선 적용/호환성 감지/라이브 에지 폴백 구현하고 테스트한다.

### 5.4 녹화 파일 내구성
- 작업 디렉터리에 영상·오디오 세그먼트/중간 파일 기록, 최종 검증 후 원자적 rename 가능하면 사용.
- 파일이 사용 중일 때 미완료로 표시하고 `COMPLETE` 상태를 먼저 기록하지 않는다.
- 갑작스러운 종료 이후 MP4가 손상될 위험이 있어 임시 컨테이너/세그먼트 보존 전략을 사용한 후 FFmpeg remux를 통해 최종 MP4 작성. 이 설계는 확정된 **최종 결과 MP4** 요구를 지키면서 복구 가능성을 높이기 위한 구현 상세이다.
- 파일의 재생 가능성 검사(FFprobe)가 실패하면 `PARTIAL` 또는 `FAILED`로 기록하고 원본 조각을 삭제하지 않는다.
- 끊긴 구간을 거짓으로 메우거나 파일을 임의 연결하지 않는다. 세그먼트별 시간 메타데이터와 누락 표시를 유지한다.

### 5.5 DVR / 다시보기 처리
- DVR 지원 시 시작 시점부터 다운로드를 시도하되 `yt-dlp --live-from-start` 성공을 보장하지 않는다.
- DVR 미지원이나 초기 구간 확보 불가능 시 현재 라이브 에지부터 녹화.
- 방송을 건너뜀/실패/누락 판정하면 replay watcher 예약.
- 종료 추정 시각부터 24시간, 최대 30분 간격 확인. 재시작 후에도 `next_check_at`과 `deadline_at` 보존. 24시간은 앱 구동 시간 합산이 아닌 벽시계 기준.
- 다시보기가 접근 가능하고 다운로드가 허용될 때 다운로드; 해당 영상이 비공개/차단/삭제/권한 부족이면 원인을 기록하고 우회하지 않음.
- 실시간 녹화 중 다시보기 다운로드를 시작하지 않음(단일 다운로드/녹화 작업 제한 권장). 대기 중인 다시보기 다운로드는 녹화 시작 시 일시 중지/대기 처리.

## 6. 상태 머신

### 6.1 방송(Broadcast.status)
- `WAITING` → `LIVE_DETECTED` → `RECORDING` → `FINALIZING` → `VERIFYING` → `COMPLETED`
- `WAITING` → `MISSED_BUSY` → `REPLAY_WAIT` → `REPLAY_DOWNLOADING` → `COMPLETED`
- `RECORDING` → `RECONNECTING` → `RECORDING`
- `RECORDING` → `INTERRUPTED` → `RECOVERING` → `RECORDING` / `REPLAY_WAIT`
- `*` → `ERROR` (복구 가능 유형은 재시도), 사용자 취소 `CANCELLED`
- `REPLAY_WAIT` → `REPLAY_EXPIRED` (24시간 만료)
- 종료 여부 판단 실패 시 `ERROR_RETRYABLE`, 단일 조회 실패로 완료 처리 금지.

### 6.2 녹화 세션(RecordingSession.status)
- `CREATED`, `RUNNING`, `RECONNECTING`, `FINALIZING`, `VERIFYING`, `COMPLETE`, `PARTIAL`, `FAILED`, `CANCELLED`
- 세션 하나에는 파일 세그먼트 1개 이상 연결 가능.
- 방송 상태는 최종 결과를 표현하고 세션은 실제 개별 녹화 시도를 표현; 상태를 혼용하지 말 것.

## 7. SQLite 데이터 모델

### broadcasts
- `id` UUID PK, `video_id` TEXT UNIQUE (활성 대기 건의 중복 규칙을 구현하기 위해 상태 기반 검증 별도), `original_url`, `title`, `channel_name`, `thumbnail_url`, `scheduled_start_at`, `actual_start_at`, `registered_at`, `status`, `preferred_quality`, `custom_filename`, `last_polled_at`, `last_error_code`, `updated_at`.
- 비고: 과거 동일 ID가 기록에 있는 것은 재등록 허용 여부가 요구상 미확정. **권장 기본**: 현재 대기/진행 중 ID에 대해서만 중복 차단, 기록의 완료 항목은 별도 세션으로 보존. 기록 정규화를 위해 `video_id UNIQUE` 제약을 전체 테이블에 걸 경우 과거 재등록 모델을 함께 설계할 것.

### recording_sessions
- `id` UUID PK, `broadcast_id` FK, `started_at`, `ended_at`, `status`, `mode` (`LIVE`/`REPLAY`), `selected_quality`, `actual_quality`, `output_path`, `duration_seconds`, `size_bytes`, `ffprobe_ok`, `failure_reason`, `created_at`, `updated_at`.

### recording_segments
- `id` UUID PK, `session_id` FK, `segment_index`, `temporary_path`, `final_path`, `started_at`, `ended_at`, `status`, `bytes_written`.

### replay_jobs
- `id` UUID PK, `broadcast_id` FK, `status`, `reason`, `created_at`, `deadline_at`, `next_check_at`, `last_attempt_at`, `attempts`, `output_path`, `error_code`.

### app_settings
- `key` TEXT PK, `value_json`, `updated_at`. 예: `save_folder`, `last_update_checked_at`.

### app_events
- `id`, `event_time`, `severity`, `category`, `broadcast_id` nullable, `session_id` nullable, `error_code`, `message`, `details_json` (민감/불필요 정보 마스킹).

- DB 경로: `%LOCALAPPDATA%/YouTubeLiveRecorder/data/app.db`
- 로그 경로: `%LOCALAPPDATA%/YouTubeLiveRecorder/logs/`
- DB WAL 및 트랜잭션 활용. 모든 시각 저장은 UTC ISO8601, UI/파일명은 Asia/Seoul로 변환.
- 마이그레이션 버전 관리 필수.

## 8. 파일명 규칙
- 기본: `{actual_start_local_date}_{sanitized_title}.mp4`
- 시작일 미확인 시: 예약 시작일(확실할 때) → 첫 라이브 감지일 → 저장일 순서의 대체값, UI에서 추정값임을 표시.
- 사용자가 이름을 수정한 경우 수정한 basename이 우선이며 `.mp4` 확장자 강제.
- `<>:"/\\|?*`, 후행 공백/마침표, Windows 예약 이름, 경로 탈출 시도 제거.
- 이름 충돌 시 기존 파일을 덮어쓰지 않고 `(2)`, `(3)` 순번 추가.
- 전체 파일 경로 길이 및 UNC/외장 드라이브 오류 대비.

## 9. 오류 분류와 복구 정책

| 코드 | 사용자 표시 | 자동 처리 |
|---|---|---|
| NETWORK_DISCONNECTED | 인터넷 연결을 확인해 주세요 | 지수 백오프 재시도, 진행 세그먼트 보존 |
| STREAM_NOT_LIVE | 아직 방송이 시작되지 않았습니다 | 60초 후 재확인 |
| STREAM_UNAVAILABLE | 방송을 볼 수 없거나 접근할 수 없습니다 | 접근 제한 우회 없이 상태/원인 안내 |
| STREAM_ENDED | 방송이 종료되었습니다 | 재확인 후 최종 저장 |
| BUSY_SINGLE_SLOT | 다른 방송 녹화 중입니다 | 이번 방송 `MISSED_BUSY`, 복구 대상 등록 |
| DISK_LOW | 저장 공간이 부족합니다 | 경고, 안전하게 기록 보존/필요 시 중단 |
| WRITE_PERMISSION_DENIED | 저장 폴더에 쓸 수 없습니다 | 설정에서 폴더 변경 안내 |
| MEDIA_TOOL_MISSING | 녹화 구성요소에 문제가 있습니다 | 번들/경로 검사 및 업데이트 안내 |
| FINALIZE_FAILED | 영상 파일 저장 중 오류가 발생했습니다 | 임시 파일 유지, 재실행 시 복구 시도 |
| VERIFY_FAILED | 저장된 파일을 검사할 수 없습니다 | 기록 `PARTIAL`/`FAILED`, 원본 보존 |
| RATE_LIMITED | 요청이 일시적으로 제한되었습니다 | 백오프 증가, 무리한 재요청 금지 |
| REPLAY_EXPIRED | 24시간 내 다시보기를 찾지 못했습니다 | 감지 종료, 기록 보존 |

- 일반적인 일시 오류: 재시도 간격 예 15s → 30s → 60s → 120s → 최대 10분. 단 방송 확인 기본 주기는 60초; 백오프 중에는 60초보다 길 수 있음.
- 녹화 재시도에는 최대 연속 실패 횟수/서킷 브레이커 설정 필요. 치명 오류에서 무한 프로세스 재시작 금지.
- 사용자에게 고급 기술 로그를 기본 노출하지 않되 내부 로컬 로그는 문제 분석용으로 보유.

## 10. 절전 방지와 트레이 동작
- 대기 항목이 있거나 녹화/복구 작업이 활성 상태면 Windows `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)`.
- 작업이 전혀 없거나 완전 종료하면 `SetThreadExecutionState(ES_CONTINUOUS)`.
- 디스플레이 관련 플래그는 설정하지 않아 모니터 자동 꺼짐 허용.
- 강제 전원 종료/사용자의 덮개 닫기 동작은 막을 수 없음.
- Qt `QSystemTrayIcon` 사용, 상태별 아이콘과 tooltip 갱신.
- X 클릭은 hide; '완전 종료'는 확인/정리 후 프로세스 종료.

## 11. 앱 업데이트 구조
- 업데이트용 HTTPS 릴리스 매니페스트 URL은 **향후 실제 배포 경로 결정 전까지 설정값/환경변수**로 둔다. 존재하지 않는 서버나 자동 배포를 가정하지 않는다.
- 릴리스 메타데이터: 버전, 다운로드 URL, SHA256, 서명(권장), 변경사항.
- 새 버전 알림 후 사용자가 다운로드/설치 승인; 녹화 중 설치 금지.
- 다운로드 파일의 무결성 검사, 잘못된 업데이트는 실행 금지.
- 1인용 로컬 프로그램이므로 별도의 계정 백엔드는 개발하지 않는다.

## 12. 패키징/설치
1. Python dependency lock, yt-dlp, FFmpeg/FFprobe 실행 파일 버전 고정.
2. PyInstaller one-folder 빌드 권장(진단·외부 바이너리 호환 및 안정성 측면).
3. Inno Setup으로 `Setup.exe` 생성, 시작 메뉴/바탕화면 바로가기 지원.
4. 앱 실행 데이터는 설치 경로가 아닌 `%LOCALAPPDATA%`에 저장.
5. 업그레이드 시 기존 DB·설정·녹화 파일 보존, 제거 시 사용자 데이터 삭제 여부 명시.
6. 외부 배포 전 FFmpeg/Qt/yt-dlp 등 구성요소 라이선스 및 고지 검토.

## 13. 수용 테스트 (Acceptance Criteria)
- AC-01: 3가지 대표 유튜브 URL 형식이 단일 video ID로 정규화되고 중복 등록 차단.
- AC-02: 방송 등록 후 60초 폴링으로 시작 감지; 실제 지연은 서비스 응답에 따라 달라질 수 있음을 UI에 표시.
- AC-03: 2개 방송 동시 시작 시 한 개만 녹화하며 다른 하나는 `MISSED_BUSY`로 기록.
- AC-04: 720p/1080p/최고 화질, 사용 불가 시 폴백과 실제 화질 기록.
- AC-05: 정상 라이브 종료 후 오디오+비디오 MP4 및 FFprobe 검사 결과 반영.
- AC-06: 수동 중지 후 잔여 데이터 최대 보존, 새 이름으로 파일 완료 또는 부분 기록.
- AC-07: 녹화 중 네트워크 끊김/복구 시 재연결하고 파일 손실을 최소화, 누락 구간 별도 표시.
- AC-08: 강제 프로세스 종료 후 다시 실행해 작업 복구 및 방송 진행 중이면 재개.
- AC-09: 놓친 방송의 허용된 다시보기 공개 후 30분 간격 재확인, 24시간 만료 시 종료.
- AC-10: 기존 라이브 영상 보존하고 다시보기는 별도 파일로 저장.
- AC-11: X 버튼은 트레이로 이동하고 감지 지속, 완전 종료는 확인과 파일 정리 실행.
- AC-12: 앱 재시작 후 대기 목록·설정 복원 및 자동 감지 재개.
- AC-13: 종료 후 대기 목록에서 완료 항목이 제거되고 기록에 출력됨.
- AC-14: 사용자 폴더/외장 드라이브 접근 불가 또는 저장 공간 부족 시 사용자에게 안내.
- AC-15: 시작/완료 알림과 완료 알림 클릭 시 탐색기 열기 동작 검증(Windows 10/11).
- AC-16: 방송 시작일로 기본 파일명 생성, 사용자 지정명 유지, Windows 금지문자/중복 충돌 처리.
- AC-17: 자동 절전 방지 활성/해제 동작과 모니터 절전 허용을 실제 Windows에서 검증.
- AC-18: 로그인/DRM/비공개 제한 영상은 우회하거나 다운로드하지 않음.
- AC-19: 설치 및 제거 후 기존 녹화 파일 불필요 삭제 없음.
- AC-20: UI 프리즈 없이 긴 방송(예: 3시간) 처리 및 안정적 상태 갱신.

## 14. Codex 개발 지시
1. 먼저 본 PRD를 읽고 요구사항 ID로 작업을 관리한다. 사용자 확정 사항을 임의로 축소하거나 확장하지 않는다.
2. 가장 먼저 앱 스켈레톤, DB 마이그레이션, URL 파서, 상태 머신 및 서비스 인터페이스를 만들고 자동화된 유닛 테스트를 추가한다.
3. yt-dlp/FFmpeg 연동은 어댑터 모듈로 분리하고, 네트워크 없는 fixture/mock 테스트를 우선 구현한다.
4. Windows에서 실제 허용된 테스트 스트림으로 통합 테스트한다. 서비스 측 제한이나 실험 기능 실패 시 부분 지원으로 정확하게 표시한다.
5. 임시 파일/부분 파일 삭제는 복구 가능성을 검증하기 전 수행하지 않는다.
6. `README.md`에 설치·사용·문제 해결·녹화 권한 안내를 한국어로 작성한다.
7. `pytest` 및 packaging 검증을 통과한 뒤 `Setup.exe`를 산출한다.
8. 불확실한 외부 업데이트 서버/배포 주소를 임의로 발명하지 않는다.

## 15. 구현 시 유의해야 할 쟁점
- 60초 폴링은 실제 녹화 시작 지연을 보장하지 않으며 서비스 응답과 재시도 시간도 추가될 수 있다.
- DVR 처음부터 녹화(`--live-from-start`)는 yt-dlp에서 실험적으로 제공하므로 항상 성공한다고 가정하지 않는다.
- 다시보기 공개 자체는 다운로드 권한 보장이 아니며, 방송 전체가 보존된다는 보장도 없다.
- 재시작 자동 복구는 **앱을 다시 실행했을 때** 동작한다. Windows 부팅 시 자동실행은 이번 버전의 요구사항이 아니다.
- 단일 작업 정책: 동시에 **녹화 1건**은 필수. 다시보기 다운로드와 녹화 충돌이 생기면 라이브 녹화 우선, 다시보기는 큐에 보관.
- 모든 구현 완료 선언에는 통합 테스트 결과와 실제 Setup.exe 경로가 필요하며 PRD만으로 프로그램이 완성된 것은 아니다.

## 16. 참고 공식 문서
- yt-dlp README: https://github.com/yt-dlp/yt-dlp (live-from-start / wait-for-video 등 동작과 버전 검증)
- Qt QSystemTrayIcon: https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QSystemTrayIcon.html
- Microsoft SetThreadExecutionState: https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate
