# Lab01Blockchain

### 1. Tổng quan
Dự án này mô phỏng một cụm RAFT 5 node (mỗi node chạy riêng một process) dùng **gRPC** để trao đổi RPC. Mục tiêu: triển khai leader election, log replication, commit bằng đa số và kiểm tra tính bền vững (durability) khi restart.

# Lab01Blockchain – Lệnh & Scripts


# 1. Yêu cầu & chuẩn bị môi trường (Windows)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install grpcio grpcio-tools pytest

# Dọn dữ liệu/logs
Remove-Item -Recurse -Force .\data
Remove-Item node-*.log -Force
Remove-Item -Recurse -Force .\artifacts
New-Item -ItemType Directory -Path data,artifacts

# Nếu xài CMD:
# rmdir /S /Q logs
# rmdir /S /Q artifacts
# mkdir logs
# mkdir artifacts

# 2. Kiểm tra port
python tools/check_ports.py
taskkill /PID <pid> /F  # kill port bị chiếm
# start_cluster.py --force để bỏ preflight port check (debug local)

# 3. Start node và cluster
python start_node.py 1            # start 1 node
python start_cluster.py            # start toàn bộ cluster 5 node
python start_cluster.py --force    # bỏ preflight port check
python run_node.py                 # chạy nhiều node trong cùng process (dev)
python tools/stop_all_nodes.py     # dừng tất cả node

# 4. Kiểm tra trạng thái node & admin endpoints (HTTP)
Invoke-RestMethod "http://127.0.0.1:6001/state"
Invoke-RestMethod "http://127.0.0.1:6001/admin/disconnect?peers=2,3"
Invoke-RestMethod "http://127.0.0.1:6001/admin/reconnect?peers=2,3"
Invoke-RestMethod "http://127.0.0.1:6001/admin/shutdown"

# 5. Gửi lệnh từ client
python raft_client.py set mykey 123
python raft_cilent.py set mykey 123  # support tên file cũ

# 6. Thay đổi số node / ports / topology
# -> sửa file config.py (NODES dict), kiểm tra port, restart cluster

# 7. Mô phỏng lỗi / Byzantine
# - Partition / blackhole: /admin/disconnect
# - Shutdown node: /admin/shutdown hoặc kill PID
# - Ép term: /admin/setterm?term=NN
# - pBFT demo: run_pbft_node.py (byzantine=(i==3))

# 8. Persistence & durability
python -m pytest tests/test_durability.py::test_durability -q

# 9. File log & artifacts
# node-1.log, node-2.log, ... 
# artifacts/<timestamp>_reason/ (dump_logs helper)

# 10. Các bước chạy step-by-step
# Mở PowerShell, di chuyển vào thư mục project
# Tạo & kích hoạt venv
# Kiểm tra port
python tools/check_ports.py

# Khởi cụm 5 node
python start_cluster.py

# Hoặc start 1 node debug
python start_node.py 1

# Xác minh trạng thái node
Invoke-RestMethod "http://127.0.0.1:6001/state"

# Gửi lệnh ví dụ
python raft_client.py set example 100

# Mô phỏng fault
# - tắt leader: /admin/shutdown
# - blackhole follower: /admin/disconnect

# Chạy test tổng quát, durability, pBFT
taskkill /F /IM python.exe
Remove-Item -Recurse -Force .\data
Remove-Item node-*.log -Force
Remove-Item -Recurse -Force .\artifacts
New-Item -ItemType Directory -Path data,artifacts
.venv\Scripts\activate

# FULL TEST (lần 1)
python -m pytest -q

# Kill python lần nữa
taskkill /F /IM python.exe

# Dọn sạch dữ liệu/logs
Remove-Item -Recurse -Force .\data
Remove-Item node-*.log -Force
Remove-Item -Recurse -Force .\artifacts
New-Item -ItemType Directory -Path data,artifacts

# Chạy DURABILITY (lần 2)
python -m pytest tests/test_durability.py::test_durability -q

# Test pBFT
python start_pbft_cluster.py
pytest -q test_pbft.py

# Khi test thất bại, kiểm tra artifacts/ và node-*.log để phân tích

### 8. Tài liệu chi tiết các file & hàm (File reference) 

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