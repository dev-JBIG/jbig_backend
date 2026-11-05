# JBIG Big Data Arena

기존 JWT로 로그인한 모든 JBIG 회원이 참가한다. 기수·최근 접속·현재 활동 여부에 따른 필터는 없다. 기존의 계정 정지/이메일 미인증에 따른 로그인 제한은 그대로 따른다. 공개명은 `참가자 0001` 같은 고정 번호이고, Django admin의 참가자 목록에서 회원 계정과 대응시킨다. 개인 리더보드만 제공하며 조별 시상은 운영진이 별도로 판별한다. 참가자 화면에 데이터 출처나 규칙 확정 대기 문구를 표시하지 않는다.

## 기본 운영값

- KST 하루 5회. 형식 검증 후 정상 접수된 제출부터 차감하며 채점 대기도 포함한다.
- CSV 최대 5,000,000 bytes. UTF-8/BOM, CRLF/LF/CR, 인용 문자를 지원한다. 헤더 두 개 외 추가 열과 중복 헤더는 거절하고 헤더 순서는 허용한다.
- Test의 모든 ID가 문자열 그대로 한 번씩 필요하다. 음수 유한 예측은 허용하며 클리핑하지 않는다.
- 같은 요청 키와 같은 파일 해시는 동일 접수다. 다른 파일에 같은 키를 재사용하면 409. 새 키의 의도적 제출은 새 횟수를 사용한다.
- Public 약 30%, Private 약 70%. 13개 설명변수 조합을 유지하고 hotel×arrival_month별로 분할한다. 분할은 등록 시 한 번 고정한다.
- 진행 중 개인별 최저 Public, 최종 본인 선택 한 건의 Private로 순위 산출. 미선택 시 최저 Public을 자동 선택한다. 동점은 접수 시각, UUID 순이다. 표시는 소수점 4자리, 정렬은 원래 점수다.
- 대기 중인 정상 접수도 최종 선택 가능하다. 마감 후 미완료·오류 채점이 있으면 최종 확정을 중단하여 선택된 제출을 임의 교체하지 않는다.
- 시작·마감은 미설정이며 기본은 준비 중. 정상 접수 시각이 `start <= accepted_at < end`일 때만 접수한다. 업로드 시작 시각이 접수를 보장하지 않는다.

## 파일 경계

세 저장소/release, `media`, `static`, nginx document root, CDN과 분리된 경로를 사용한다. 로컬 기본 경로는 저장소들의 형제인 `../.arena-private/` 아래 세 디렉터리다. 운영은 세 환경 변수를 명시해야 하며 기본 공개 미디어 스토리지를 재사용하지 않는다.

```text
ARENA_PARTICIPANT_ROOT=/srv/jbig-arena/participant
ARENA_SUBMISSION_ROOT=/srv/jbig-arena/submissions
ARENA_GRADING_ROOT=/srv/jbig-arena/grading
```

웹 프로세스에는 앞의 두 변수만 주고, `ARENA_GRADING_ROOT`는 비워 둔다. 정답·분할·manifest를 읽는 코드는 `scoring.py`, `data_setup.py`, 서버 관리 명령에 한정된다. HTTP views는 이 모듈을 import하지 않는다. `/api/arena/downloads/`는 `train|test|sample`만 허용하며 임의 경로·정답·분할·제출 원본 다운로드 API는 제공하지 않는다.

기존 nginx API proxy 경로에서 CSV 5,000,000 bytes와 multipart 부가 정보를 수신할 수 있도록 요청 본문 상한은 예를 들어 `client_max_body_size 6m;`로 둔다. 실제 파일의 정확한 5MB 제한은 애플리케이션이 적용한다. 비공개 디렉터리에 nginx alias나 공개 CDN을 연결하지 않는다.

운영에서는 웹 계정과 `jbig-grader` 계정을 분리해야 한다. `grading` 디렉터리와 파일은 grader 소유 0700/0600, 웹 계정은 접근 불가로 둔다. `participant`는 웹·등록 명령이 읽을 수 있어야 한다. 일반 제출은 디렉터리 0750·파일 0640으로 만들고 웹·grader만 속한 전용 그룹으로 공유한다. 웹 서비스의 primary group과 submissions 루트의 setgid 그룹을 이 전용 그룹으로 설정하고 UMask는 0027로 둔다. 원본 데이터 등록 파일의 기본 모드는 0600이므로 참가자 배포 파일에만 운영자가 그룹 읽기를 부여한다. grader에 웹 `.env` 읽기 권한을 추가하지 말고 전용 EnvironmentFile을 사용한다.

실제 정답으로 만든 서버 검증 제출은 `grading/<version>/verification/` 아래에 0700/0600으로 보관한다. 일반 제출 공유 경로에 정답 검증 CSV를 넣지 않는다.

grader EnvironmentFile에는 기존 DB 접속 변수, `SECRET_KEY`, 세 Arena 경로와 `JBIG_ENV_ONLY=1`을 둔다. 이 모드는 `.env` 읽기를 생략하고 제공된 환경 변수로 서버 모드를 사용한다. 실제 DB 엔진·주소·계정·비밀번호·배포 경로는 운영 환경에 맞춘다. 로컬 SQLite 검토용 프로세스에는 `FORCE_LOCAL=1`을 쓴다. 운영 다중 프로세스 동시성은 운영 DB 엔진에서도 별도로 검증한다.

## 데이터 등록 (운영진 전용)

기존 DB 백업·마이그레이션 뒤, 정답 접근 권한을 가진 서버 계정으로 실행한다. 지정된 원본의 행·열·해시와 ID 대응을 검사하고 참가자 파일은 바이트 그대로 복사한다. 실제 Test ID와 예측 0으로 제출 예시를 생성한다. 정답·분할 파일은 공개 저장소/배포 archive에 넣지 않는다.

```bash
python manage.py migrate
python manage.py arena_setup \
  --train /secure/import/participant/train.csv \
  --test /secure/import/participant/test.csv \
  --labels /secure/import/organizer/test_labels.csv \
  --data-version hotel-adr-v1
```

등록은 대회를 자동 개방하지 않는다. 동일 버전·동일 파일로 재실행 가능하며 기존 버전의 내용을 교체할 수 없다. 접수 이후 다른 데이터 버전으로 변경할 수 없다. `grading/<version>/manifest.json`은 전체 파일 해시, 실제 분할 수·층별 집계·seed·알고리즘 버전과 평가 버전을 기록한다. 이 파일과 분할 ID는 서버 내부에만 둔다.

실제 고정 분할: Public 3,064 / Private 7,149, 전체 10,213. 비율은 약 30.001% / 69.999%. 동일 설명변수 그룹은 8,231개이며 분할 양쪽에 겹치는 그룹은 없다.

## 채점과 복구

```bash
python manage.py arena_worker --once
python manage.py arena_worker
python manage.py arena_worker --once --retry-errors
```

첫 명령은 현재 대기 작업을 처리하고 종료한다. 두 번째는 DB 작업을 2초 간격으로 확인한다. 오류 접수는 원래 UUID·접수일·횟수를 유지한다. 원인을 복구한 후 세 번째 명령으로 재처리한다. 워커가 작업 중 죽으면 5분 lease 만료 후 같은 접수를 다시 가져온다. 늦게 완료된 이전 워커는 점유 토큰 검사로 결과를 덮어쓸 수 없다. DB 커밋 응답 유실 시 접수 파일을 지우지 않고 같은 요청 키로 복구한다.

systemd 예시는 `deploy/jbig-arena-worker.service.example`에 있다. 실제 current-release 경로와 계정·환경 파일을 맞춘 후 `jbig-arena-worker.service`로 설치한다. 기존 CI는 이 서비스가 설치된 경우 백엔드 배포 후 함께 재시작한다. 서비스 미설치 상태에서는 채점이 대기 상태로 남으므로 개방 전 워커 동작을 확인한다. SQLite를 운영에 쓸 경우 별도 DB 파일 경로의 쓰기 권한과 단일 워커 운용도 검토한다.

## 0점 검증과 최종 결과

```bash
python manage.py arena_verify
python manage.py arena_finalize
python manage.py arena_check_results
```

`arena_verify`는 로그인 불가능한 전용 서버 검증 계정을 만들고 정답 원본/순서 변경 제출이 Public·Private 모두 0인지 검사한다. 정답을 브라우저로 전송하지 않는다. 검증 참가자는 Public·최종 리더보드와 인원 집계에서 제외한다. 반복 실행은 고정 요청 키를 재사용하므로 중복 차감하지 않는다.

Django admin에서 일정과 상태를 설정하고 개방한다. 마감 뒤 대기/오류 채점을 모두 처리한 다음 `arena_finalize`로 결과를 확정한다. 수동 선택/자동 선택 사유, 제출 UUID, 데이터 버전·원본 해시와 연결된 결과 snapshot을 DB에 고정한다. 반복 확정 명령은 같은 결과를 반환한다. 최종 결과가 확정되기 전에는 Private 점수가 참가자에게 반환되지 않는다. 확정 후에도 본인의 선택된 제출 및 최종 순위의 집계 점수만 반환한다.

`arena_check_results`는 선택된 원본 파일과 고정된 정답·분할을 다시 읽어 점수와 동점 순서를 재계산하고 최종 snapshot과 비교한다. 파일 해시·점수·순위가 달라지면 성공으로 보고하지 않는다.

```bash
FORCE_LOCAL=1 python manage.py test competitions
FORCE_LOCAL=1 python manage.py test
```

실제 운영 전 남은 항목: 시작·마감 시각, 상금/수상 상세 공지, 비공개 OS 권한/백업/nginx 경계, 운영 DB에서 경쟁 요청 테스트, worker 설치와 실제 서비스 계정 복구 리허설. 로그인 회원 전용 리더보드와 고정 참가자 번호 표시는 현재 기본값이다. 참가자 안내에는 구현·인프라 설정 사항을 표시하지 않는다.
