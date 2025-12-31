# Lab01Blockchain

### 1. Tổng quan
Dự án này mô phỏng một cụm RAFT 5 node (mỗi node chạy riêng một process) dùng **gRPC** để trao đổi RPC. Mục tiêu: triển khai leader election, log replication, commit bằng đa số và kiểm tra tính bền vững (durability) khi restart.

---

### 2. Chuẩn bị môi trường (Windows — cmd / PowerShell / VS Code Terminal)

- Tạo và kích hoạt virtual environment:
  - PowerShell:
    ```powershell
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    ```
  - cmd:
    ```cmd
    python -m venv .venv
    .\.venv\Scripts\activate.bat
    ```
  - VS Code: mở Terminal (PowerShell hoặc cmd) và chạy các lệnh trên.

- Cài dependencies:
  ```bash
  pip install -r requirements.txt
  # Nếu không có file requirements.txt: pip install grpcio grpcio-tools pytest
  ```

---

### 3. Chạy chương trình

- Chạy **một node** (có thể dùng `run_node.py` để tự gán NODE_ID hoặc đặt biến môi trường):
  - PowerShell:
    ```powershell
    $env:NODE_ID = 1
    python run_node.py
    ```
  - cmd:
    ```cmd
    set NODE_ID=1
    python run_node.py
    ```
  - Hoặc dùng `start_node.py` (không cần gán biến môi trường):
    ```bash
    python start_node.py 1
    ```

- Khởi **cụm 5 node** (script sẽ kiểm tra port trống trước khi start):
  ```bash
  python start_cluster.py
  ```
  - Nếu bạn đang debug local và cần bỏ qua kiểm tra port: `python start_cluster.py --force` (chỉ dùng khi bạn chắc chắn không lo ngại xung đột port).

- Gửi lệnh tới cluster (CLI client):
  ```bash
  python raft_client.py set mykey 123
  # hoặc (backwards-compatible): python raft_cilent.py set mykey 123
  ```
  - CLI hỗ trợ lệnh nhiều thành phần (multi-word).
  - Exit code: `0` = thành công, `1` = thất bại.

---

### 4. Endpoints quản trị & debug (HTTP)
Mỗi node cũng chạy một HTTP status server (port = gRPC_port + 1000). Ví dụ node chạy gRPC tại `127.0.0.1:5001` sẽ có status tại `http://127.0.0.1:6001/state`.

- GET `/state` — xem `role`, `leader_id`, `term`, `log_len`, `commit_index`, `kv_snapshot`, `blackholed_peers`.
- GET `/admin/disconnect?peers=ID1,ID2` — mô phỏng phân mảnh: node sẽ 'blackhole' các peer chỉ định.
- GET `/admin/reconnect?peers=ID1,ID2` — bỏ blackhole.
- GET `/admin/clear` — xóa tất cả blackholes.
- GET `/admin/shutdown` — shutdown node.
- GET `/admin/setterm?term=NN` — đặt term cho node (dùng để test tình huống bất thường).

Ví dụ (PowerShell):
```powershell
Invoke-RestMethod http://127.0.0.1:6001/state
Invoke-RestMethod "http://127.0.0.1:6001/admin/disconnect?peers=2,3"
```

---

### 5. Các test và cách chạy chúng ✅
- Chạy toàn bộ test suite (pytest):
  ```bash
  python -m pytest -q
  ```
- Chạy riêng test durability (kịch bản start → commit → kill → restart → verify):
  ```bash
  python -m pytest tests/test_durability.py::test_durability -q
  ```
- Test CLI (ví dụ):
  ```bash
  python -m pytest tests/test_cli.py::test_raft_cilent_cli_multword -q
  ```
- Chạy pBFT:
  ```
  python start_pbft_cluster.py 
  ```

Ghi chú: Trước khi chạy `tests/test_durability.py`, đảm bảo không có tiến trình khác đang dùng các port mặc định (5001..5005 và 6001..6005). Sử dụng `python tools/check_ports.py` để kiểm tra port.

---

### 6. Những gì đã được triển khai (tóm tắt)
- Mạng 5 node chạy độc lập (process) với gRPC.
- RAFT core:
  - RequestVote, AppendEntries, leader election, heartbeat.
  - Log replication với probe/repair, commit by majority.
  - Leader-only `ClientAppend` RPC (tối ưu cho client requests) và AppendEntries fallback.
- Persistence: KV store file-backed (atomic write) — dùng để kiểm thử durability.
- Admin HTTP endpoints cho testing (state, disconnect, reconnect, shutdown, setterm).
- Tests: unit tests, functional tests, durability test integrated into pytest.
- CI: workflow có kiểm tra port preflight và chạy тестs + durability in integration job.

**Chưa làm (nâng cao):** pBFT (điểm cộng) — có thiết kế và test‑plan trong báo cáo nhưng chưa có mã thực thi.

---

### 7. Debug, preflight và các thao tác chuẩn trước khi test (rõ ràng hơn)

#### A. Kiểm tra port và dọn sạch tiến trình chiếm port (preflight)
Trước khi chạy `start_cluster.py` hoặc `tests/test_durability.py`, **bắt buộc** đảm bảo các port mặc định (gRPC: 5001..5005 và HTTP status: 6001..6005) đang trống.

- Kiểm tra port bằng script có sẵn:
  ```bash
  python tools/check_ports.py
  ```
  Script sẽ liệt kê các port đang bận và PID (nếu có).

- Nếu port bị chiếm, kill tiến trình đó (Windows):
  - Tìm PID (từ script ở trên) rồi kill:
    ```cmd
    taskkill /PID <pid> /F
    ```
  - Hoặc PowerShell:
    ```powershell
    Stop-Process -Id <pid> -Force
    ```

- Lưu ý: tránh dùng `taskkill /F /IM python.exe` trừ khi bạn muốn dừng tất cả tiến trình Python đang chạy (có thể kill nhầm test runner).

- Nếu bạn chỉ muốn nhanh (chỉ khuyến nghị cho debug local), bạn có thể bỏ qua kiểm tra preflight bằng `python start_cluster.py --force`, nhưng **không dùng** trên CI.


#### B. Vị trí file logs và những log quan trọng cần kiểm tra
- Vị trí file logs: các file log được tạo trong **thư mục project root** với tên `node-1.log`, `node-2.log`, … (stdout/stderr của từng node).
- Các log bạn nên kiểm tra khi debug:
  - Các thông báo bầu leader: `ELECTED LEADER` hoặc `[Node X] -> CANDIDATE` / `-> FOLLOWER`.
  - AppendEntries/ClientAppend: các message về replicate attempts, resp.success, resp.term và các ngoại lệ trong handler (stacktrace được ghi vào node-*.log).
  - Commit messages: thông báo `Entry committed at index` và lệnh đã bị commit.
  - Replication errors / probe messages: thông báo `replicate_to_peer` / `probe` logs để hiểu mismatch hoặc retry.

#### C. Cách start nhiều node cùng lúc (manual vs script)
- Cách đơn giản (script quản lý background processes):
  ```bash
  python start_cluster.py
  ```
  Script này sẽ khởi 5 process (với PIDs được in ra). Chỉ cần có 1 terminal.

- Chạy thủ công (mỗi node 1 terminal):
  - Mở nhiều terminal (PowerShell / cmd / VS Code Terminal), mỗi terminal đặt NODE_ID khác nhau rồi chạy:
    ```powershell
    $env:NODE_ID = 1
    python run_node.py
    ```
    terminal thứ 2:
    ```powershell
    $env:NODE_ID = 2
    python run_node.py
    ```
  - Hoặc dùng `start_node.py` để khởi từng node: `python start_node.py 1` (mỗi terminal một command).

- Chạy background trên Windows (CMD):
  ```cmd
  start "Node1" cmd /k "set NODE_ID=1 && python run_node.py"
  ```
  (mỗi lệnh `start` sẽ mở một cửa sổ terminal mới và giữ tiến trình chạy)

#### D. Các tham số cấu hình quan trọng và cách điều chỉnh
Các tham số nằm trong `config.py` ảnh hưởng đến tính ổn định/độ tin cậy trong test:
- `ELECTION_TIMEOUT_MIN` và `ELECTION_TIMEOUT_MAX` (giây):
  - Quyết định thời gian timeout cho election. Nếu quá nhỏ -> khả năng split-vote cao; nếu quá lớn -> re-election chậm.
  - Đã đặt mặc định hơi lớn hơn để giảm split-election trong CI: (ví dụ 1.5 / 3.0).
- `HEARTBEAT_INTERVAL` (giây):
  - Tần suất leader gửi heartbeat. Giá trị nhỏ giúp phát hiện nhanh thất bại nhưng tăng overhead.

Thay đổi: chỉnh trực tiếp trong `config.py` và restart node(s) để áp dụng.

#### E. Reset cluster / Cleanup trước khi rerun test
Trước khi chạy lại durability test, nên xóa dữ liệu cũ và logs để tránh chạy trên trạng thái còn sót:
- Xóa thư mục dữ liệu (KV store):
  - cmd:
    ```cmd
    rmdir /S /Q data
    del node-*.log
    ```
  - PowerShell:
    ```powershell
    Remove-Item -Recurse -Force .\data
    Remove-Item node-*.log -Force
    ```
- Xác minh port trống: `python tools/check_ports.py`.
- Sau cleanup, khởi `start_cluster.py` rồi chạy `tests/test_durability.py`.

---

### 8. Tài liệu chi tiết các file & hàm (File reference) 🔎
Dưới đây là danh sách **các file/ thư mục** chính trong repository và mô tả ngắn về **mục đích** cùng các hàm/ class quan trọng để giúp bạn nắm nhanh cấu trúc dự án.

- `config.py`  
  - Mục đích: cấu hình cluster (danh sách node, quorum) và các hằng thời gian RAFT (election timeout, heartbeat interval).  
  - Biến quan trọng: `NODES`, `MAJORITY`, `ELECTION_TIMEOUT_MIN`, `ELECTION_TIMEOUT_MAX`, `HEARTBEAT_INTERVAL`.  
  - Hàm: `random_election_timeout()` để lấy ngẫu nhiên timeout trong khoảng.

- `raft_state.py`  
  - Mục đích: nội dung state của một node RAFT (terms, votes, log, commit_index) và xử lý logic cốt lõi của RAFT.  
  - Class `RaftState`:
    - `reset_election_timeout(min_timeout, max_timeout)` — đặt deadline election mới.
    - `election_timeout_reached()` — kiểm tra timeout.
    - `become_follower(term, leader_id=None)`, `become_candidate()`, `become_leader()` — chuyển vai trò và cập nhật term.
    - `on_request_vote(term, candidate_id)` — xử lý RequestVote RPC (trả vote_granted, term).
    - `on_append_entries(...)` — xử lý AppendEntries RPC (heartbeat hoặc replication), áp log, cập nhật commit_index.
    - `debug_status()` — in trạng thái nội bộ để debug.
  - Ghi chú: hệ thống **ghi log** khi phát hiện term bất thường (>=1000); stack traces và trạng thái chi tiết được ghi ở mức DEBUG/WARNING vào `node-*.log` (không in trực tiếp ra stdout).

- `raft_node.py`  
  - Mục đích: thực thi một node RAFT đầy đủ (gRPC server, peer connections, election & heartbeat loops, replication).  
  - Class `RaftNode` (hàm nổi bật):
    - `__init__()` — khởi tạo node, KV store, status HTTP server, apply loop.
    - `ping_peers()` — probe nhanh peer bằng AppendEntries để đánh giá reachable.
    - `RequestVote(request, context)` / `AppendEntries(request, context)` — RPC handlers (nếu chạy trực tiếp như service).
    - `replicate_to_peer(peer_id, ...)` — logic replicate logs tới một peer (fast-path + probe + repair), xử lý higher-term detection.
    - `commit_by_majority()` — commit entries khi đa số đã ack.
    - `apply_committed_loop()` — apply committed entries vào KV store (persist).
    - `ClientAppend(request, context)` — leader-only handler cho client-submitted commands (append -> replicate -> wait commit).
    - `election_loop()`, `start_election()` — tiến hành election.
    - `heartbeat_loop()` — gửi heartbeat hoặc catch-up replication định kỳ.
    - `start_status_server()` — chạy HTTP `/state` và `/admin` endpoints (disconnect/reconnect/clear/shutdown/setterm).
  - Telemetry: `next_index`, `match_index`, `replication_errors`, `peer_failure_counts`, `last_heartbeat_ack` giúp debug replication health.

- `raft_service.py`  
  - Mục đích: wrapper gRPC service triển khai RPCs bằng cách sử dụng `RaftState` (được dùng khi dùng `RaftService` server class).
  - `RaftService` triển khai: `RequestVote`, `AppendEntries`, `ClientAppend` (một số tối ưu replication và log append).

- `raft_rpc.py`  
  - Mục đích: implementation thay thế/đơn giản của các RPC (nhẹ hơn) — giữ các handler như `RequestVote` / `AppendEntries` theo kiểu trực tiếp tương tự `raft_service`.

- `raft_client.py`  
  - Mục đích: client tiện ích để gửi lệnh tới cluster (tìm leader + ClientAppend fallback AppendEntries).  
  - Hàm chính: `find_leader()` (dùng HTTP `/state` để tìm leader đáng tin cậy), `send_command(command, max_attempts, backoff)` — thực thi command tới leader với retry, fallback khi cần.

- `raft_cilent.py`  
  - Mục đích: CLI tiện dụng (tên cũ/typo support) — gọi `raft_client.send_command` để gửi lệnh từ command line (đã sửa để dùng client đúng thay vì gửi trực tiếp AppendEntries không an toàn).

- `kv_store.py`  
  - Mục đích: lưu KV persist (file-backed JSON) và cung cấp `set/get` để đảm bảo durability across restarts.

- `start_node.py`  
  - Mục đích: khởi gRPC server cho 1 node trong 1 process (kèm healthcheck bind địa chỉ để tránh lỗi 0.0.0.0 trên Windows). Ghi stdout/stderr vào `node-<id>.log`.

- `start_cluster.py` và `start_cluster_stagger.py`  
  - Mục đích: script orchestrator để start 5 node (kèm preflight port check), in PIDs, đợi `/state` health, chờ leader stability; `--force` để bỏ qua preflight khi debug local.
  - Chức năng thêm: in tail logs nếu process exit ngay, set `GRPC_VERBOSITY=error` cho child processes để giảm noise.

- `run_node.py`, `run_smoke.py`  
  - `run_node.py`: helper để chạy nhiều node trong cùng process (multi-thread) — hữu ích cho phát triển nhanh.  
  - `run_smoke.py`: script chạy kịch bản smoke test (sanity checks).

- `tools/`  (thư mục helper test/fixture):
  - `tools/check_ports.py` — kiểm tra port 5001..5005 & 6001..6005 có bị chiếm.
  - `tools/fault_tests.py` — helper test để probe states, tìm leader, kill/restart, simulate faults.
  - `tools/admin.py` — wrapper nhỏ cho admin HTTP endpoints.
  - `tools/inspect_states.py`, `run_fault_tests.py`, `debug_durability.py`, `stop_all_nodes.py`, `run_leader_crash.py` — các kịch bản hỗ trợ debugging & fault injection.

- `tests/`  
  - `tests/test_durability.py` — kịch bản E2E: start cluster, commit key, kill all, restart, verify key persisted. Tạo artifacts trên thất bại.
  - `tests/test_replicate_functional.py` — kiểm tra replicate multi-node scenario (functional).
  - `tests/test_replicate_unit.py` — unit tests cho `replicate_to_peer` và xử lý higher-term; test nhỏ giúp tách logic replicate.
  - `tests/test_cli.py` — test client/CLI interactions.
  - `tests/test_apply_local.py`, `tests/test_state.py` — các unit test khác cho apply loop và state transitions.

- `proto/raft.proto` và `raft_pb2.py`, `raft_pb2_grpc.py`  
  - Mô tả: định nghĩa protobuf cho các RPC RAFT (RequestVote, AppendEntries, LogEntry). `pb2` / `pb2_grpc` là files generated.

- `node-*.log` & `artifacts/`  
  - `node-*.log`: stdout/stderr của từng node (rất hữu ích khi debug start/term/replication issues).
  - `artifacts/`: chứa snapshot logs và file chụp lỗi khi test thất bại (timestamped).

- `pbft_block.py`
  - Mục đích: định nghĩa **block tối giản** dùng cho các kịch bản kiểm tra PBFT (Practical Byzantine Fault Tolerance), chủ yếu để test durability và logic đồng thuận. Không chứa state phức tạp, chỉ giữ `height` và hash.  
  - Class `Block`:  
    - `__init__(height: int, prev_hash: str)` — khởi tạo block với `height` và hash của block trước (`prev_hash`). Tự động tính toán hash block hiện tại (`self.hash`).  
    - `_compute_hash()` — tính toán SHA-256 hash dựa trên `height` và `prev_hash`.  
    - `__repr__()` — hiển thị block dạng ngắn gọn, ví dụ `Block(height=3, hash=abc123)`, hữu ích khi debug logs.  

- `pbft_message.py`
  - Mục đích: định nghĩa các **message types** và **class message** cơ bản cho PBFT, dùng để broadcast block giữa các node trong quá trình test.  
  - Message Types:  
    - `PRE_PREPARE` — bước chuẩn bị trước khi commit block.  
    - `PREPARE` — bước chuẩn bị đồng thuận từ đa số node.  
    - `COMMIT` — bước commit block khi đa số node đồng thuận.  
  - Class `PBFTMessage`:  
    - `__init__(msg_type: str, block: Any, sender: int)` — khởi tạo message với loại (`msg_type`), block đính kèm (`block`) và node gửi (`sender`).  
    - `__repr__()` — hiển thị dạng ngắn gọn: `PBFTMessage(type=PREPARE, height=3, sender=1)`, hữu ích khi debug logs. 

- `pbft_node.py`
  - Mục đích: triển khai node PBFT đơn giản, hỗ trợ các kịch bản **primary**, **Byzantine**, và **durability tests**. Dùng để simulate broadcast message, voting, và commit block giữa các node.  
  - Class `PBFTNode`:
    - `__init__(node_id: int, total_nodes: int, is_primary: bool = False, byzantine: bool = False)`  
      - Khởi tạo node với `node_id`, tổng số node `total_nodes`, cờ `is_primary`, và cờ `byzantine`.  
      - Tính toán `f = (n-1)//3` cho quorum BFT.  
      - Khởi tạo các cấu trúc lưu votes (`prepare_votes`, `commit_votes`), block finalized, blacklist, v.v.  
    - `connect(peers: List[PBFTNode])` — kết nối node với danh sách peers để broadcast message.  
    - `broadcast(msg: PBFTMessage)` — gửi message đến tất cả peers (ngoại trừ bản thân).  
    - `start_pbft(block: Any)` — entry point của primary node để bắt đầu PRE-PREPARE cho block mới.  
    - `receive(msg: PBFTMessage)` — nhận message và dispatch tới handler tương ứng (`_on_pre_prepare`, `_on_prepare`, `_on_commit`).  
    - `_on_pre_prepare(msg: PBFTMessage)` — xử lý PRE-PREPARE message, broadcast PREPARE tới peers, kiểm tra quorum.  
    - `_on_prepare(msg: PBFTMessage)` — xử lý PREPARE message, cập nhật votes, kiểm tra quorum.  
    - `_check_prepare_quorum(block: Any)` — kiểm tra nếu đã đủ quorum PREPARE (≥ 2f+1), gửi COMMIT và gọi `_check_commit_quorum`.  
    - `_on_commit(msg: PBFTMessage)` — xử lý COMMIT message, cập nhật votes và kiểm tra quorum commit.  
    - `_check_commit_quorum(block: Any)` — kiểm tra nếu đủ quorum COMMIT, đánh dấu block finalized và log thông tin.  
- `start_pbft_cluster.py`:
  - Mục đích: entry point để **khởi chạy một PBFT node** trong một process.

---

### 9. Cấu trúc thư mục
## 📂 Project Structure

```text
LAB01BLOCKCHAIN/
├── proto/           
├── scripts/                
├── tests/                                                
├── tools/                  
│
├── pbft_*.py               
│   ├── pbft_block.py       
│   ├── pbft_message.py     
│   └── pbft_node.py        
│
├── raft_*.py               
│   ├── raft_node.py        
│   ├── raft_client.py      
│   ├── raft_state.py       
│   └── raft_service.py     
│
├── start_*.py              
│   ├── start_cluster.py   
│   ├── start_node.py   
│   ├── start_pbft_cluster.py 
│   └── start_cluster_stagger.py 
│
├── run_*.py                
│   ├── run_node.py         
│   ├── run_smoke.py 
│   └── run_pbft_node.py         
│
├── config.py               
├── kv_store.py             
├── probe_state.py                       
└── README.md               