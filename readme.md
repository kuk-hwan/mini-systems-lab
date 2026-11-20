# Mini DBMS · C Web Server

이 브랜치는 기존 Mini DBMS와, POSIX 소켓으로 직접 구현한 **C 웹 서버 + Reverse Proxy**를 함께 보관합니다. 두 프로젝트는 독립적으로 실행합니다.

| 프로젝트 | 내용 | 실행·구조·검증 |
|---|---|---|
| `mini-webserver/` | C11, GET·POST, 정적 파일, 스레드 풀, Reverse Proxy, Round-Robin | [웹 서버 README](mini-webserver/README.md) |
| `mini-dbms/` | Python SQL 처리기, B+ 트리, 파일 저장, Thread Pool API | [DBMS README](mini-dbms/README.md) |

## C 웹 서버 시작

Linux·macOS·WSL2 Ubuntu에서 실행합니다.

```sh
cd mini-webserver
make
./build/mini-webserver --port 8080 --root public
```

[http://localhost:8080](http://localhost:8080)에서 요청 데모를 확인합니다. [백엔드 A/B를 실행하는 Reverse Proxy 예시](mini-webserver/README.md#reverse-proxy와-ab-백엔드-실행), [함수 실행 흐름](mini-webserver/docs/architecture.md), [검증 기록](mini-webserver/docs/verification.md)도 제공합니다.

## 기존 Mini DBMS

SQL을 직접 해석하고 테이블 파일에 행을 저장하는 Python 기반 데이터베이스입니다.

![Mini DBMS 계층도. Phase 3 API, Phase 1 SQL 처리, Phase 2 인덱스, 파일 저장 계층 순서와 선형 탐색 경로](mini-dbms/docs/architecture.png)

API에서 인덱스를 사용하는 ID 조회는 **Phase 3 스레드 풀 → Phase 1 SQL 처리기 → Phase 2 B+ 트리** 순서로 이어집니다. B+ 트리는 행이 있는 파일 위치를 반환합니다. 인덱스가 적용되지 않는 조회는 테이블 파일을 순서대로 읽습니다. CLI로 `.sql` 파일을 실행하면 Phase 1의 같은 SQL 처리기로 들어갑니다.

## 바로 실행하기

~~~powershell
cd mini-dbms
python -m mini_dbms.cli examples/demo.sql
~~~

[전체 실행 방법과 API 예제](mini-dbms/README.md) · [100만 건 성능 비교 결과](mini-dbms/reports/benchmark.json)
