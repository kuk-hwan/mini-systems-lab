# Mini Redis

Python 표준 라이브러리만으로 만든 독립형 키-값 캐시입니다. 이 폴더는 자체 해시 테이블과 로컬 HTTP API를 제공합니다.

- 해시 테이블은 FNV-1a로 버킷을 정하고, 같은 버킷에 들어간 키는 목록에서 비교합니다. 부하율이 0.75를 넘으면 버킷을 두 배로 늘립니다.
- TTL은 초 단위입니다. 생략하면 만료 시각을 두지 않습니다. 조회할 때 만료된 키를 제거하고, 통계 조회·스냅샷 저장 시에도 만료된 항목을 정리합니다.
- 스냅샷을 선택하면 유효한 항목과 만료 시각을 파일에 보관합니다.

## 실행하기

Python 3.11 이상에서 저장소 루트를 기준으로 실행합니다.

```sh
python mini-redis/server.py
```

서버 주소는 `http://127.0.0.1:8787`입니다. 다른 포트는 `--port`로 지정합니다.

## 시간 제한 퀴즈

서버를 켜고 브라우저에서 [퀴즈](http://127.0.0.1:8787/)를 엽니다. Redis 개념 5문제를 문제당 25초 안에 풀 수 있습니다.

1. 문제를 시작하면 서버가 힌트 키를 **TTL 10초**로 저장합니다. 화면에 `SET`이 표시됩니다.
2. 10초 안에 **힌트 조회**를 누르면 서버가 값을 꺼냅니다. 유효한 힌트가 있으면 `GET · HIT`가 표시됩니다.
3. 힌트 타이머가 만료된 뒤 다시 조회하면 Mini Redis가 만료된 키를 지우고 `GET · MISS`가 표시됩니다. 문제의 제한 시간이 남아 있으면 답을 계속 제출할 수 있습니다.

문제 전환, 힌트 조회, 답안 마감과 채점, 점수 집계, HTML 생성은 Python 서버가 맡습니다. 브라우저는 HTML 폼과 CSS로 화면과 카운트다운을 표시합니다. 퀴즈는 같은 Mini Redis 엔진을 사용하며, 연습용 라운드와 힌트는 일반 키-값 API의 데이터 및 스냅샷과 별도 공간에 보관합니다.

## HTTP API 예시

다음은 PowerShell에서 상품 목록을 저장하고 조회한 뒤 삭제하는 예입니다.

```powershell
$keyUrl = 'http://127.0.0.1:8787/api/kv/products'
$body = @{ value = @('상품 A', '상품 B'); ttl = 60 } | ConvertTo-Json -Compress
Invoke-RestMethod -Method Put -Uri $keyUrl -ContentType 'application/json; charset=utf-8' -Body $body
Invoke-RestMethod -Method Get -Uri $keyUrl
Invoke-RestMethod -Method Delete -Uri $keyUrl
```

| 개념 | HTTP API | 응답 또는 동작 |
| --- | --- | --- |
| SET | `PUT /api/kv/<키>` | JSON의 `value`와 선택 사항인 `ttl`을 저장 |
| GET | `GET /api/kv/<키>` | `found: true`면 HIT, `found: false`면 MISS |
| DEL | `DELETE /api/kv/<키>` | 키를 삭제하고 `deleted`를 반환 |
| 통계 | `GET /api/metrics` | HIT, MISS, 만료, 버킷 통계 |
| 상태 | `GET /api/health` | 서버 실행 여부 |

상품 목록이 바뀌었을 때 애플리케이션에서 해당 키를 삭제하면 다음 조회는 MISS가 됩니다. 애플리케이션은 그때 최신 목록을 준비해 캐시를 다시 채울 수 있습니다.

## 선택 사항: 스냅샷

```sh
python mini-redis/server.py --snapshot mini-redis/.data/cache.json
```

시작 시 스냅샷에서 아직 유효한 키를 복원합니다. 실행 중 `POST /api/cache/snapshot`이나 정상 종료 시점에 스냅샷을 갱신합니다. 비정상 종료 시 마지막 스냅샷 이후 변경은 유실될 수 있습니다.

이 서버는 학습용 로컬 HTTP API입니다. 실제 Redis 클라이언트가 쓰는 RESP 대신 JSON으로 요청합니다.

## 테스트

```sh
python -m unittest discover -s mini-redis -v
```
