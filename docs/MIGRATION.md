# 이력 보존 방식과 브랜치 대응표

통합일: 2026-11-20. 새 저장소는 `kuk-hwan/mini-systems-lab`입니다. 세 원본 저장소에는 변경·삭제·Archive 작업을 하지 않았습니다.

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

검사기는 브랜치별 원본 SHA 일치, 원본 커밋 79개가 main에서 도달 가능한지, Git 객체 무결성, 선택 시 원격 저장소의 실제 참조까지 확인합니다. 원본 세 저장소의 참조를 다시 조회해서 가져온 시점과 변경되지 않은 것도 업로드 후 확인합니다.

## 기존 저장소와 GitHub 정보

원본 저장소는 계속 사용할 수 있습니다. 통합 저장소와 자동으로 동기화되지는 않으므로 향후 변경을 어느 저장소에서 개발할지 정해야 합니다. 이후에는 통합 main에서 작업하고 원본 보존 브랜치를 수정하지 않는 방식을 권장합니다.

이슈·PR·댓글·스타·기존 Actions 실행 결과·협업자 권한은 Git 커밋의 일부가 아니므로 이번 이력 통합에 포함하지 않았습니다. GitHub에 새 권한이나 협업자 설정을 복사하지 않았습니다.
