# 통합 main 실행 검증

> 아래 네 프로젝트의 표는 최초 통합 시점의 검증 기록입니다. 이후 C 웹 서버는 [전용 저장소](https://github.com/kuk-hwan/mini-webserver)로 분리했습니다. 현재 이 저장소의 전체 검사·CI는 React·Redis·DBMS·이력 검증을 수행합니다. 웹 서버의 새 검사 결과는 [전용 Actions](https://github.com/kuk-hwan/mini-webserver/actions)에서 확인합니다.

검증일: 2026-11-20. 원본 보존 브랜치의 엔진 코드를 바꾸지 않고 통합 main의 새 경로에서 검사했습니다.

## 이력 무결성

- 원본 저장소 3개, 브랜치 10개, 고유 커밋 79개를 보존했습니다.
- 원본 브랜치와 새 접두사 브랜치의 HEAD SHA가 모두 같습니다.
- 원본 79개 커밋을 통합 main에서 모두 도달할 수 있습니다.
- `git fsck --full`로 Git 객체 무결성을 확인했습니다.
- 실제 목록은 [원본 명세](import-manifest.json), 기계 판독용 검사 결과는 [history-verification.json](history-verification.json)에 있습니다.

로컬 검사 결과 파일은 로컬 검증을 기록합니다. 업로드 후 `python scripts/verify_history.py --remote origin --fsck`로 GitHub 쪽 참조도 별도로 대조합니다.

## 실행 결과

| 대상 | 새 폴더에서 실행한 명령 | 결과 |
|---|---|---|
| React 엔진 | `npm run check` | 41개 테스트 + strict TypeScript + Vite 빌드 통과 |
| React 브라우저 | `npm run test:e2e` | 데스크톱·모바일 Chromium 총 8개 통과 |
| Redis | `python -m unittest discover -s .` | 캐시·TTL·퀴즈·결과 목록 API 18개 통과 |
| DBMS | `python -m unittest discover -s tests` | SQL·B+ 트리·파일 저장·동시 API 13개 통과 |
| C 웹 서버 | `make test smoke` | 단위 assertion 92개 + 통합 40개 + 실제 curl 통과 |
| C 메모리 | `make sanitize-test valgrind` | ASan·UBSan·누수 검사 통과, 프록시·백엔드 메모리 오류 및 추가 FD 0 |

React는 Windows Node.js 24에서 빌드하고 실제 Chromium에서 검사했습니다. Python은 Windows Python 3.14에서 검사했습니다. C 서버는 WSL2 Ubuntu에서 빌드·실행·메모리 검사를 했습니다. 새 통합 CI에는 Linux/macOS C 검사와 Linux React·Python·이력 검사를 구성했습니다.

### 실제 확인한 화면 동작

- DOM 실험실의 HTML 편집·Patch·이전/다음·키 기반 순서 변경.
- Hooks 작업 보드의 작업 추가·검색·배칭·저장.
- 카드 16장, 같은 DOM 유지, 두 번째 카드 선택 시 attempts와 카드 상태의 배칭, 불일치 타이머, Phase 1·2 검사기.
- Redis 퀴즈의 힌트 TTL, 한 번만 연장, 한 번만 조회, 시간 만료, 채점, 결과 목록 MISS/HIT·새 점수 저장 후 무효화.
- DBMS의 CLI 재실행 저장 유지, 인덱스/선형 탐색, 파일 바이트 위치, 동시 INSERT와 ID 유일성.
- C 서버의 정적 자산, GET/POST, A/B 백엔드 중계, 연결 재사용, 오류·타임아웃·종료 처리.

### 통합 중 보완한 부분

1. React 저장소 안에 있던 최신 Redis 퀴즈를 명시적으로 반영해 기능 누락을 막았습니다.
2. React 내부의 중복 Redis·DBMS 폴더는 통합 main의 전용 폴더로 정리했습니다. 원본 보존 브랜치에는 그대로 있습니다.
3. C 서버의 테스트 클라이언트가 빠른 503 응답 뒤 half-close할 때 생기는 ENOTCONN 타이밍을 처리했습니다. 실제 HTTP 상태 검사는 그대로 수행합니다. C 서버 엔진을 바꾸거나 실패한 테스트를 건너뛰지 않았습니다.
4. README 실행 경로·통합 CI 작업 디렉터리·npm 캐시 경로를 새 구조에 맞췄습니다.

## 범위

기존 C 서버의 12,000요청 벤치마크 결과와 DBMS의 100만 건 측정 파일은 원본에서 가져온 기록입니다. 이번 통합 확인에서 다시 같은 부하·대용량 삽입을 측정한 것은 아닙니다. 테스트를 통과한 실행 버전은 통합 main이며, 다른 팀원의 원본 보존 브랜치까지 모두 재빌드했다고 주장하지 않습니다.

이력 검증과 실행 테스트는 별개입니다. 원본 브랜치가 그대로 보존됐다는 사실과, 통합 폴더의 앱이 동작한다는 사실을 각각 검사했습니다.
