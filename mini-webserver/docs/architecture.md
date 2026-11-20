# 구조와 실행 흐름

## 1. 서버 시작과 연결 접수

```text
main()
  config_init()           포트·루트·라우트 해석, 백엔드 주소 확인
  net_listen()            getaddrinfo → socket → SO_REUSEADDR → bind → listen
  pool_init()             고정 수의 pthread 작업자 생성
  poll()                  리스너 또는 종료 신호 self-pipe 기다림
  accept()                새로운 connfd 획득
  pool_submit(connfd)     제한된 큐로 소유권 전달
```

모든 소켓은 O_NONBLOCK입니다. `accept`는 대기 중 연결을 수락하다 EAGAIN이면 poll로 돌아갑니다. 통신 작업자는 읽기·쓰기 준비가 안 됐을 때만 poll로 기다립니다. 이것은 스레드 풀 모델에 타임아웃 가능한 I/O를 사용한 것이며 C10K 이벤트 루프를 구현한 것은 아닙니다.

## 2. 작업자에서 HTTP 요청 읽기

```text
worker()
  큐 mutex 잠금 → connfd 하나 꺼냄 → 잠금 해제
  handle_connection()
    read_request()
      read_head()             CRLF 단위로 헤더 끝까지 읽기
      parse_request_head()    메서드·URI·버전
      parse_headers()         Host·CL·Connection 등 확인
      필요하면 100 Continue
      stream_exact()          본문 CL 바이트 읽기
```

stream_t는 이미 받은 바이트 중 아직 사용하지 않은 부분을 보관합니다. 한 번의 recv에서 헤더·본문·다음 요청 일부까지 들어와도 각 요청 경계대로 꺼냅니다. Connection: close인 경우 또는 에러로 연결을 닫을 때 남은 요청을 실행하지 않습니다.

`poll`의 시간 제한은 매번 5초로 초기화하지 않습니다. 요청 시작 시의 절대 deadline에서 현재 시간을 빼므로 느리게 한 바이트씩 보내는 클라이언트가 작업자를 무한히 붙잡을 수 없습니다. 다만 작업자 수 자체를 모두 차지하는 연결은 있을 수 있어 큐 제한·deadline이 함께 필요합니다.

## 3. 정적 파일

```text
decode_path() → 퍼센트 디코딩·위험 경로 검사
serve_static()
  static_open() → root_fd 기준, 경로 요소마다 openat(O_NOFOLLOW)
  fstat() → 일반 파일·읽기 권한·길이 확인
  mime_type() → Content-Type 선택
  response_head() → 상태·헤더
  read() → send_all() 반복 → 파일 FD 닫기
```

리소스가 없으면 404, 디렉터리·심볼릭 링크·권한 문제는 403, 내부 파일 처리 실패는 500입니다. 파일 읽기와 네트워크 쓰기는 부분 처리·EINTR를 고려합니다. 파일이 응답 중 변경되어 헤더의 길이만큼 읽을 수 없으면 연결을 끊어 불완전한 응답을 표시합니다.

## 4. Reverse Proxy

```text
route_match() → 가장 긴 경로 접두사 선택
route_next() → mutex 아래 Round-Robin 선택
net_connect() → 백엔드용 socket → non-blocking connect → poll → SO_ERROR
forward_request()
  Host·CL·Connection 재작성
  hop-by-hop 헤더 제거
  본문 바이트 전달
upstream_head() → 상태·헤더 파싱
Content-Length / chunked / EOF 기준으로 본문 완성
response_head() → 새 응답 경계 생성
send_all() → 클라이언트로 본문 전달
백엔드 FD·본문 버퍼 정리
```

클라이언트는 프록시의 존재를 몰라도 됩니다. 내부 백엔드의 주소는 CLI 설정에서 정합니다. 클라이언트가 Host나 URI로 임의 외부 주소를 선택하는 Forward Proxy가 아닙니다.

백엔드가 잘못된 응답이나 짧은 본문을 보내면 502, deadline을 넘으면 504입니다. HTTP 응답을 다 읽기 전까지 클라이언트에 성공 헤더를 보내지 않으므로 실패를 오류 응답으로 바꿀 수 있습니다. 대신 응답 8 MiB 상한과 메모리 비용이 생깁니다. 요청 실패 시 POST를 다른 백엔드에 다시 보내지 않습니다.

## 5. 소유권과 종료

| 자원 | 소유권·정리 |
|---|---|
| 리스너·정적 루트 FD | main/config에서 열고 종료 시 닫음 |
| 큐 안의 connfd | 큐가 소유, 종료 시 큐가 닫음 |
| 큐에서 꺼낸 connfd | worker가 소유, handle_connection 종료 후 닫음 |
| 요청 본문 | read_request가 할당, 요청 종료마다 request_free |
| 백엔드 FD·응답 버퍼 | serve_proxy가 모든 성공·실패 경로에서 정리 |
| 라운드 로빈 번호 | 라우트 mutex로 보호 |
| 종료 여부 | C11 atomic_bool, signal handler의 sig_atomic_t와 구분 |

SIGINT/SIGTERM handler는 종료 플래그와 non-blocking pipe 쓰기만 합니다. 메인 루프가 접수를 멈추고, 큐에 남은 연결을 닫고, 진행 중 요청이 완료되거나 deadline에 도달할 때까지 작업자를 join합니다. 종료 신호는 작업 스레드에서 차단합니다. SIGPIPE는 무시하고 send 실패를 정상 오류 경로로 처리합니다.

## 6. 세 가지 동시성 모델 비교

| 모델 | 장점 | 비용 |
|---|---|---|
| fork 기반 | 주소 공간 분리, 한 작업의 메모리 오류 영향 축소 | 프로세스 생성·메모리·자식 회수 |
| 이 구현의 스레드 풀 | 작업자 수 제한, 비교적 단순한 코드, 데이터 공유 가능 | 잠금 설계, 느린 연결이 작업자 차지 |
| 이벤트 루프 | 많은 유휴 연결을 적은 스레드로 관리 | 요청·쓰기·백엔드 연결 상태를 나눠 관리해야 함 |

이 과제의 첫 구현은 스레드 풀로 실행 흐름을 명확하게 만들고 실제 검증을 갖추는 데 중점을 뒀습니다.
