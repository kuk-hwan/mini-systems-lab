# 이력 보존 방식과 브랜치 대응표

통합일: 2026-11-20. 현재 저장소는 [kuk-hwan/mini-systems-lab](https://github.com/kuk-hwan/mini-systems-lab)입니다. 통합·보존 검증 후 사용자가 기존 세 저장소를 직접 삭제했습니다. 삭제 후 통합 저장소를 새로 clone하여 원본 브랜치·커밋·파일이 그대로 남아 있는지 다시 확인했습니다.

## 이후 변경 · 웹 서버 전용 저장소 분리

2026-11-20에 웹 서버를 [kuk-hwan/mini-webserver](https://github.com/kuk-hwan/mini-webserver)로 옮겼습니다. 전용 저장소를 새로 clone해 39개 원본 파일의 보존과 Git 객체 무결성을 확인한 후 통합 main의 해당 폴더·C 검사 workflow를 제거했습니다. 웹 서버 관련 커밋 4개를 추출했고, 새 경로 때문에 달라진 커밋 번호는 [전용 분리 기록](https://github.com/kuk-hwan/mini-webserver/blob/main/docs/MIGRATION.md)에서 확인합니다.

원본 보존 브랜치와 아래 79개 원본 커밋의 검증 명세는 그대로 유지합니다. 아래 파일 배치는 최초 통합 시점 기록이며, 현재 실행 구조는 [루트 README](../README.md)를 기준으로 확인합니다.

## 무엇을 가져왔나요?

| 원본 | 브랜치 | 해당 저장소에서 도달 가능한 커밋 |
|---|---:|---:|
| `kuk-hwan/mini-react-fiber-lab` | 1 | 17 |
| `kuk-hwan/mini-redis` | 4 | 46 |
| `kuk-hwan/mini-DBMS` | 5 | 16 |
| 합계 | 10 | 고유 커밋 79 |

가져온 시점에 세 원본에는 태그가 없었습니다. Git이 공개하는 현재 참조에서 도달 가능한 모든 커밋을 수집했습니다. 원격에서 이미 삭제되어 도달할 수 없는 커밋까지 복구했다는 뜻은 아닙니다. 실제 목록과 40자리 커밋 번호는 [import-manifest.json](import-manifest.json)에 있습니다.

## 이름이 겹치는 브랜치 구분

| 원본 저장소 | 원본 브랜치 | 통합 저장소의 보존 브랜치 | 원래 HEAD |
|---|---|---|---|
| React | `main` | `react/main` | `49bebac` |
| Redis | `main` | `redis/main` | `d321e2a` |
| Redis | `BurningWings` | `redis/BurningWings` | `ec26db9` |
| Redis | `CatIsApple` | `redis/CatIsApple` | `c87d673` |
| Redis | `feat/kuk-hwan/mini-redis` | `redis/feat/kuk-hwan/mini-redis` | `22cb5f2` |
| DBMS | `main` | `dbms/main` | `210c011` |
| DBMS | `BurningWings` | `dbms/BurningWings` | `f072741` |
| DBMS | `CatIsApple` | `dbms/CatIsApple` | `77d7406` |
| DBMS | `kuk-hwan` | `dbms/kuk-hwan` | `45b6450` |
| DBMS | `feat/kuk-hwan/c-web-server` | `dbms/feat/kuk-hwan/c-web-server` | `39c4f34` |

`main`이 새 통합 브랜치이며, 위 10개 브랜치는 원본 커밋을 그대로 가리킵니다. 새 폴더 경로를 과거 커밋에 강제로 적용하는 history rewrite나 squash를 하지 않았습니다.

## main은 어떻게 연결했나요?

1. 세 저장소를 전체 mirror로 내려받아 모든 브랜치·커밋 객체를 확보했습니다.
2. 원본 브랜치를 프로젝트 접두사가 붙은 브랜치로 그대로 가져왔습니다.
3. 프로젝트별 import 커밋의 부모로 이전 통합 main과 원본의 모든 브랜치 HEAD를 연결했습니다.
4. import 커밋의 파일 트리에 선택한 실행 버전을 새 폴더로 배치했습니다.
5. 최신 퀴즈 사본 반영·중복 폴더 정리·실행 경로 문서화는 별도의 새 커밋으로 남겼습니다.

따라서 원본 79개 커밋은 보존 브랜치뿐 아니라 `main`의 조상으로도 남습니다. 원본 커밋의 파일 경로는 원래대로 유지되므로, 이전 파일별 변경은 원본 보존 브랜치에서 원래 경로로 조회할 수 있습니다.

```sh
git log --all --graph --oneline
git log origin/redis/feat/kuk-hwan/mini-redis -- mini-redis/quiz.py
git show 39c4f34:mini-webserver/src/main.c
```

## main에 선택한 파일 버전

- React: `react/main`의 루트 파일을 `mini-react-fiber-lab/`로 배치했습니다.
- Redis: `redis/feat/kuk-hwan/mini-redis`의 `mini-redis/`를 가져온 뒤, React `main`에 있는 더 최신 퀴즈 사본을 명시적으로 반영했습니다. TTL 표시·5초 연장·1회 조회·결과 목록 캐시 기능을 유지합니다.
- DBMS: `dbms/feat/kuk-hwan/c-web-server`의 `mini-dbms/`를 가져왔습니다.
- C 웹 서버: 같은 브랜치의 `mini-webserver/`를 가져왔습니다.
- React 안에 중복 보관되던 Redis·DBMS 폴더는 통합 main에서 정리했습니다. 해당 원본 파일들은 `react/main`과 과거 커밋에서 그대로 볼 수 있습니다.

실행 가능한 한 버전과 모든 원본 브랜치를 함께 보관한 것이며, 서로 다른 팀원 구현의 코드를 한 실행 엔진으로 섞은 것은 아닙니다.

## 검증 재현

```sh
git fetch origin
python scripts/verify_history.py --fsck
python scripts/verify_history.py --remote origin --fsck
```

검사기는 통합 시 기록한 명세를 기준으로 브랜치별 원본 SHA 일치, 원본 커밋 79개가 main에서 도달 가능한지, Git 객체 무결성, 선택 시 통합 원격 저장소의 실제 참조까지 확인합니다. 삭제한 원본 저장소에 접속하지 않아도 검증할 수 있습니다.

삭제 후 새로 받은 사본은 삭제 전 mirror 백업과도 대조했습니다. 원본 브랜치 10개의 HEAD와 파일 트리가 모두 같고, 원본 커밋 79개·파일 내용 객체 465개·트리 객체 263개가 모두 존재했습니다. `git fsck --full --strict`를 통과했으며, 삭제한 저장소나 다른 로컬 저장소의 객체에 의존하지 않습니다.

## 기존 저장소와 GitHub 정보

기존 세 저장소는 삭제되었습니다. 실행할 최신 코드는 [통합 main](https://github.com/kuk-hwan/mini-systems-lab/tree/main)에, 원래 버전은 [React 보존 브랜치](https://github.com/kuk-hwan/mini-systems-lab/tree/react/main), [Redis 보존 브랜치](https://github.com/kuk-hwan/mini-systems-lab/tree/redis/feat/kuk-hwan/mini-redis), [DBMS·웹 서버 보존 브랜치](https://github.com/kuk-hwan/mini-systems-lab/tree/dbms/feat/kuk-hwan/c-web-server)에 있습니다. 이후에는 통합 main에서 새 작업 브랜치를 만들고 원본 보존 브랜치를 수정하지 않습니다.

[import-manifest.json](import-manifest.json)에 남은 예전 저장소 이름·주소는 가져온 출처를 기록한 검증 자료입니다. 이 명세와 보존 브랜치의 과거 README는 원본 이력을 유지하기 위해 변경하지 않습니다. 현재 실행 방법은 [루트 README](../README.md)를 기준으로 확인합니다.

이슈·PR·댓글·스타·기존 Actions 실행 결과·협업자 권한은 Git 커밋의 일부가 아니므로 이번 이력 통합에 포함하지 않았습니다. GitHub에 새 권한이나 협업자 설정을 복사하지 않았습니다.
