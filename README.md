# Mini Systems Lab

**직접 만든 Mini React · Mini Redis · Mini DBMS를 한 저장소에서 실행하고 공부하는 시스템 구현 모음입니다.**

세 원본 저장소의 **브랜치 10개와 고유 커밋 79개**를 커밋 번호 변경 없이 보존했습니다. 기존 세 저장소는 삭제되었으며, 앞으로는 **이 저장소의 `main`**에서 실행·개발합니다. 이전 버전·팀원의 다른 구현은 `react/*`, `redis/*`, `dbms/*` 보존 브랜치에서 확인할 수 있습니다. 삭제 후 새로 clone해 브랜치·커밋·파일 보존과 Git 객체 무결성을 다시 확인했습니다.

[이력 보존과 브랜치 대응표](docs/MIGRATION.md) · [원본 커밋 목록](docs/import-manifest.json) · [실행 검증](docs/VERIFICATION.md) · [GitHub Actions](https://github.com/kuk-hwan/mini-systems-lab/actions)

[폴더 구조](#폴더-구조) · [빠른 시작](#빠른-시작) · [전체 검사](#한-곳에서-검사하기) · [보존 브랜치](#어떤-브랜치를-사용하면-되나요)

## 프로젝트 둘러보기

| 프로젝트 | 직접 구현한 핵심 | 실행 결과 | 자세한 설명 |
|---|---|---|---|
| `mini-react-fiber-lab/` | Virtual DOM, Diff·Patch, Fiber, State, Hooks, Batching | 4×4 카드 짝 맞추기와 렌더링 검사기 | [React README](mini-react-fiber-lab/README.md) |
| `mini-redis/` | 해시 테이블, TTL, 원자적 카운터, 캐시 무효화, 스냅샷 | 시간 제한 퀴즈·힌트·결과 목록 HIT/MISS | [Redis README](mini-redis/README.md) |
| `mini-dbms/` | SQL 파서, JSONL 저장, 메모리 B+ 트리, 스레드 풀 | CLI SQL 처리와 SQL API | [DBMS README](mini-dbms/README.md) |

프로젝트들은 각각 독립적으로 실행합니다. Redis 퀴즈의 SQLite 점수 저장소는 퀴즈의 데이터 보관용이며, 직접 만든 Mini DBMS와는 별개입니다.

## 폴더 구조

```text
mini-systems-lab/
├── mini-react-fiber-lab/    TypeScript · 카드 게임 · 렌더링 검사기
├── mini-redis/              Python · 캐시 엔진 · 퀴즈
├── mini-dbms/               Python · SQL · B+ 트리 · API
├── docs/                   통합 경위 · 원본 이력 · 검증 기록
├── scripts/                이력 검증 · 전체 검사 명령
├── .github/workflows/      세 프로젝트와 이력의 자동 검사
└── README.md               전체 안내 · 실행 시작점
```

## 빠른 시작

### 준비할 것

| 실행할 프로젝트 | 필요한 환경 | 접속 주소 또는 사용 방법 |
|---|---|---|
| Mini React | Node.js 24 권장 · npm | [카드 게임 · 5173](http://127.0.0.1:5173) |
| Mini Redis | Python 3.11 이상 · 표준 라이브러리 | [시간 제한 퀴즈 · 8787](http://127.0.0.1:8787) |
| Mini DBMS | Python 3.11 이상 · 표준 라이브러리 | CLI 출력 또는 `POST http://127.0.0.1:8796/api/sql` |

React만 `npm ci`로 개발 도구를 설치합니다. 두 Python 프로젝트에는 별도의 `pip install`이 필요하지 않습니다.

### 저장소 받기

```sh
git clone https://github.com/kuk-hwan/mini-systems-lab.git
cd mini-systems-lab
```

아래 세 프로젝트의 명령은 **각각 새 터미널에서 `mini-systems-lab` 루트 폴더를 시작 위치로** 사용합니다. 서버를 실행한 터미널은 그대로 두고, 종료하려면 `Ctrl+C`를 누릅니다. 모든 프로젝트를 동시에 켤 필요는 없습니다.

### 1. Mini React · 카드 짝 맞추기

저장소 루트에서 React 폴더로 이동해 실행합니다.

```sh
cd mini-react-fiber-lab
npm ci
npm run dev
```

[http://127.0.0.1:5173](http://127.0.0.1:5173)에서 카드를 고르고 오른쪽 위 **렌더링 검사기**를 열어 상태 변경 → Diff → 실제 DOM 변경을 확인합니다.

같은 서버에서 [HTML 실험실](http://127.0.0.1:5173/#lab)과 [Hooks 작업 보드](http://127.0.0.1:5173/#hooks)도 사용할 수 있습니다. 배포 파일은 React 폴더에서 `npm run build`로 생성한 `dist/`에 있습니다.

![카드 게임과 렌더링 검사기](mini-react-fiber-lab/docs/images/memory-game.png)

### 2. Mini Redis · 시간 제한 퀴즈

Python 3.11 이상에서 저장소 루트를 기준으로 실행합니다.

```sh
python mini-redis/server.py --port 8787
```

[http://127.0.0.1:8787](http://127.0.0.1:8787)에서 문제를 풀며 **힌트 TTL·문제당 1회 조회·한 번만 5초 연장·최근 결과의 HIT/MISS**를 확인합니다. 점수는 `mini-redis/.data/quiz-results.sqlite3`에 저장됩니다. 선택 사항인 캐시 스냅샷과 키-값 HTTP API는 [Redis README](mini-redis/README.md)에 있습니다.

### 3. Mini DBMS · SQL 실행과 API

새 터미널에서 저장소 루트를 기준으로 실행합니다.

```sh
cd mini-dbms
python -m mini_dbms.cli examples/demo.sql
python -m mini_dbms.server --port 8796 --workers 4
```

CLI는 상품 예제를 저장·조회한 뒤 종료하고, 다음 명령이 API 서버를 시작합니다. 기본 데이터는 `mini-dbms/.data/db/` 아래 JSONL 파일에 남습니다. 같은 데이터 폴더를 여러 프로세스에서 동시에 열지 않습니다.

**다른 PowerShell 터미널**에서 다음 요청을 보내면 API 응답을 확인할 수 있습니다. DBMS는 웹페이지 대신 SQL의 실행 결과를 JSON으로 반환합니다.

```powershell
$query = @{ sql = 'SELECT * FROM products WHERE id = 2' } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8796/api/sql -Method Post -ContentType 'application/json' -Body $query |
  ConvertTo-Json -Depth 8
```

요청에 `use_index = $false`를 함께 넣으면 같은 ID 조회를 선형 탐색으로 비교할 수 있습니다. 자세한 SQL 문법·B+ 트리·100만 건 측정 방법은 [DBMS README](mini-dbms/README.md)에 있습니다.

![Mini DBMS의 API·SQL 처리·인덱스·파일 저장 계층](mini-dbms/docs/architecture.png)

## 별도 저장소 · C 웹 서버

C11/POSIX 웹 서버는 전용 저장소 **[kuk-hwan/mini-webserver](https://github.com/kuk-hwan/mini-webserver)**로 옮겼습니다. 소스·테스트·정적 데모·측정 기록과 관련 변경 이력을 가져갔으며, 웹 서버 개발과 자동 검사는 그 저장소에서 진행합니다.

- [웹 서버 실행 방법과 Reverse Proxy](https://github.com/kuk-hwan/mini-webserver#readme)
- [분리한 파일과 커밋 대응표](https://github.com/kuk-hwan/mini-webserver/blob/main/docs/MIGRATION.md)

통합 저장소 `main`에서는 `mini-webserver/` 폴더를 제거했습니다. 이동 전 파일은 [이동 전 커밋](https://github.com/kuk-hwan/mini-systems-lab/tree/6253cbc1ec8649075e95c62a91324cef6ebfb82b/mini-webserver)과 기존 보존 브랜치에 그대로 남습니다.

## 한 곳에서 검사하기

React 폴더의 `npm ci`를 먼저 완료한 뒤 저장소 루트에서 실행합니다.

```sh
python scripts/check_all.py

# 실제 데스크톱·모바일 Chromium까지 검사
cd mini-react-fiber-lab
npx playwright install chromium
cd ..
python scripts/check_all.py --e2e
```

전체 검사 명령은 이 저장소의 React·Redis·DBMS와 원본 이력을 검사합니다. 웹 서버는 전용 저장소에서 `make test smoke`로 검사하며, 더 이상 이 명령에 WSL이나 C 빌드 도구가 필요하지 않습니다.

개별 검사 명령은 다음과 같습니다. **실행 위치** 폴더로 이동한 뒤 명령을 입력합니다.

| 대상 | 실행 위치 | 검사 명령 |
|---|---|---|
| React 단위 검사·타입 검사·빌드 | `mini-react-fiber-lab/` | `npm run check` |
| React 실제 브라우저 | `mini-react-fiber-lab/` | `npm run test:e2e` · Chromium 설치 필요 |
| Redis 엔진·퀴즈 API | `mini-redis/` | `python -m unittest discover -s . -v` |
| DBMS SQL·인덱스·API | `mini-dbms/` | `python -m unittest discover -s tests -v` |

통합 시 검증 결과는 [실행 검증 문서](docs/VERIFICATION.md), 최신 커밋의 자동 검사 결과는 [GitHub Actions](https://github.com/kuk-hwan/mini-systems-lab/actions)에서 확인합니다.

이력만 확인하려면 다음 명령을 사용합니다.

```sh
python scripts/verify_history.py --fsck
python scripts/verify_history.py --remote origin --fsck
```

두 번째 명령은 GitHub의 브랜치도 원래 커밋 번호와 일치하는지 확인합니다. 일반 clone은 원본 보존 브랜치를 `origin/react/*` 등의 원격 추적 참조로 가져오며, 검증 스크립트는 이 형태도 확인합니다.

## 어떤 브랜치를 사용하면 되나요?

- **실행·새 개발:** `main`에서 시작합니다.
- **원래 React 저장소:** [`react/main`](https://github.com/kuk-hwan/mini-systems-lab/tree/react/main).
- **원래 Redis 저장소:** [`redis/main`](https://github.com/kuk-hwan/mini-systems-lab/tree/redis/main), [`redis/BurningWings`](https://github.com/kuk-hwan/mini-systems-lab/tree/redis/BurningWings), [`redis/CatIsApple`](https://github.com/kuk-hwan/mini-systems-lab/tree/redis/CatIsApple), [`redis/feat/kuk-hwan/mini-redis`](https://github.com/kuk-hwan/mini-systems-lab/tree/redis/feat/kuk-hwan/mini-redis).
- **원래 DBMS 저장소:** [`dbms/main`](https://github.com/kuk-hwan/mini-systems-lab/tree/dbms/main), [`dbms/BurningWings`](https://github.com/kuk-hwan/mini-systems-lab/tree/dbms/BurningWings), [`dbms/CatIsApple`](https://github.com/kuk-hwan/mini-systems-lab/tree/dbms/CatIsApple), [`dbms/kuk-hwan`](https://github.com/kuk-hwan/mini-systems-lab/tree/dbms/kuk-hwan), [`dbms/feat/kuk-hwan/c-web-server`](https://github.com/kuk-hwan/mini-systems-lab/tree/dbms/feat/kuk-hwan/c-web-server).

원본 보존 브랜치에는 **원래 파일 구조와 원래 커밋**이 있습니다. 통합 `main`의 새 폴더 구조와 다릅니다. 이 브랜치들을 수정하면 보존 검증이 실패하므로 새 기능은 `main`에서 만든 작업 브랜치에 추가합니다.

## 출처와 범위

현재 실행 코드는 [Mini React](mini-react-fiber-lab/), [Mini Redis](mini-redis/), [Mini DBMS](mini-dbms/) 폴더에 있습니다. [C 웹 서버](https://github.com/kuk-hwan/mini-webserver)는 전용 저장소에서 관리합니다. 삭제된 원본 저장소의 코드는 위 보존 브랜치에서 계속 확인할 수 있습니다. 원래 작성자·커미터·메시지·커밋 내용은 그대로 보존합니다. 각 구현의 출처·기존 라이선스는 원래 브랜치와 해당 파일을 기준으로 확인합니다. 통합 작업으로 전체 원본을 새 라이선스로 변경하지 않았습니다.

이번 작업은 Git 코드·브랜치·이력 통합입니다. 원본 GitHub의 이슈·PR·스타·Actions 실행 기록을 새 저장소로 이동한 것은 아닙니다. 기본 테스트 대상은 통합 `main`의 세 프로젝트이며, 보존된 다른 팀 브랜치들의 모든 구현을 다시 검증했다는 뜻은 아닙니다.
