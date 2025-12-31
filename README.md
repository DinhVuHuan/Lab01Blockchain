# Lab01Blockchain

### 1. Tổng quan
Dự án này mô phỏng một cụm RAFT 5 node (mỗi node chạy riêng một process) dùng **gRPC** để trao đổi RPC. Mục tiêu: triển khai leader election, log replication, commit bằng đa số và kiểm tra tính bền vững (durability) khi restart.

---
1. Yêu cầu & chuẩn bị môi trường (Windows)
Python 3.11 (recommend) và pip.
Tạo virtual environment và kích hoạt (PowerShell)
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
Cài dependencies:
  pip install grpcio grpcio-tools pytest
Dọn dữ liệu/logs (nên làm trước khi chạy test durability):
  Remove-Item -Recurse -Force .\data
  Remove-Item node-*.log -Force
  Remove-Item -Recurse -Force .\artifacts
  New-Item -ItemType Directory -Path data,artifacts
(Nếu xài CMD thì chạy lệnh: rmdir /S /Q logs rmdir /S /Q artifacts mkdir logs mkdir artifacts)
2. Kiểm tra port (bắt buộc trước khi start cluster trên CI)
Project sử dụng các port gRPC mặc định 5001..5005 và HTTP status 6001..6005.
Chạy script kiểm tra port:
  python tools/check_ports.py
Nếu có port bị chiếm, kill tiến trình tương ứng (Windows):
  taskkill /PID <pid> /F
Ghi chú: `start_cluster.py` thực hiện preflight kiểm tra port; dùng `--force` để bỏ kiểm tra (chỉ dùng debug local).
3. Cách start node và cụm node
Start một node trong process riêng (recommended):
  python start_node.py 1
Start toàn bộ cluster (mặc định 5 node) bằng script orchestrator (mỗi node là process riêng):
  python start_cluster.py
  # Bỏ preflight port check (debug local):
  python start_cluster.py --force
Chạy nhiều node trong cùng một process (phục vụ phát triển):
  python run_node.py
Dừng tất cả node (script helper):
  python tools/stop_all_nodes.py
4. Kiểm tra trạng thái node & admin endpoints (HTTP)
Mỗi node chạy một HTTP status server tại gRPC_port + 1000. Ví dụ node gRPC 127.0.0.1:5001 -> status http://127.0.0.1:6001/state.
Các endpoint hữu dụng (được implement trong RaftNode.start_status_server):
GET /state — trả JSON gồm: role, leader_id, term, log_len, commit_index, last_applied, blackholed_peers, kv_snapshot, next_index, match_index, replication_errors.
GET	/admin/disconnect?peers=ID1,ID2 — node sẽ thêm peer vào blackholed_peers và bỏ qua replicate tới peer đó.
GET	/admin/reconnect?peers=ID1,ID2 — loại peer khỏi blackholed_peers.
GET	/admin/clear — xóa mọi blackhole.
GET	/admin/shutdown — tắt node (gọi graceful stop).
GET	/admin/setterm?term=NN — đặt current_term (bị giới hạn: từ chối giá trị lớn quá >=1000).
Ví dụ PowerShell:
Invoke-RestMethod "http://127.0.0.1:6001/state"
Invoke-RestMethod "http://127.0.0.1:6001/admin/disconnect?peers=2,3"
Invoke-RestMethod "http://127.0.0.1:6001/admin/reconnect?peers=2,3"
Invoke-RestMethod "http://127.0.0.1:6001/admin/shutdown"
5. Gửi lệnh từ client
Dùng client CLI wrapper:
python raft_client.py set mykey 123
  # hoặc (hỗ trợ tên file cũ):
  python raft_cilent.py set mykey 123
Hàm chủ chốt gửi lệnh: raft_client.send_command(command, max_attempts=3, backoff=0.5).
send_command thực hiện find_leader() (dùng /state) rồi gọi ClientAppend RPC (fallback AppendEntries nếu server trả UNIMPLEMENTED).
6. Cách thay đổi số node / ports / topology
Mở file cấu hình: [config.py](config.py)
Sửa NODES (dict) theo định dạng node_id: "host:port" (ví dụ thêm 6: "127.0.0.1:5006").
NUM_NODES, ALL_NODES và MAJORITY được tính tự động từ NODES.
Sau khi chỉnh NODES:
Đảm bảo các port mới không trùng (dùng tools/check_ports.py).
Restart toàn cluster (kill tiến trình cũ, sau đó python start_cluster.py).
Lưu ý: code hiện tại giả định các node id là liên tiếp 1..N ở nhiều script; nếu thay đổi phức tạp hơn (ví dụ id không liên tiếp), kiểm tra `start_cluster.py` và `tests` để đảm bảo tương thích.
7. Mô phỏng lỗi / nút độc hại (Byzantine)
Partition / blackhole: dùng /admin/disconnect trên node A để khiến node A bỏ replicate tới một số peer. Việc này mô phỏng mất kết nối một chiều.
Shutdown node: /admin/shutdown hoặc kill PID.
Ép term để kích thích election: /admin/setterm?term=NN.
pBFT demo (mô phỏng Byzantine node):
File demo: run_pbft_node.py (tạo PBFTNode với byzantine=(i == 3) trong ví dụ).
Để thay node gian lận, sửa run_pbft_node.py hoặc pbft_node.py.
8. Persistence & durability
KV store file-backed: mỗi node lưu dữ liệu ở data/node_<ID>.json bằng class KVStore (file: kv_store.py).
Hàm: KVStore.set(key, value) và KVStore.get(key).
Durability test (kịch bản test sẵn có): [tests/test_durability.py](tests/test_durability.py)
Mô tả: start cluster, gửi set dur_key 42, kill PIDs, restart cluster, kiểm tra dur_key tồn tại trong kv_snapshot trả bởi /state.
Chạy bằng:
python -m pytest tests/test_durability.py::test_durability -q
9. File log & artifacts
Logs của node khi start bằng start_node.py: node-1.log, node-2.log, ...
Khi test thất bại, tests/test_durability.py có helper dump_logs() để copy logs vào artifacts/<timestamp>_reason/.
10. Các bước chạy cụ thể (step-by-step)
Mở PowerShell, di chuyển vào thư mục project.
Tạo và kích hoạt venv (như ở mục 1).
(CI) Chạy python tools/check_ports.py để đảm bảo các port 5001..5005 và 6001..6005 trống.
Khởi cụm 5 node:
  python start_cluster.py
Hoặc start 1 node để debug:
  python start_node.py 1
Xác minh trạng thái node (ví dụ node 1):
  Invoke-RestMethod "http://127.0.0.1:6001/state"
Gửi lệnh ví dụ:
  python raft_client.py set example 100
Kiểm tra kv_snapshot trong /state của các node để xác nhận commit.
Mô phỏng fault: tắt leader bằng /admin/shutdown hoặc blackhole follower bằng /admin/disconnect.
Chạy test tổng quát, chạy test durability và pBFT:
Mở terminal (Powershell/CMD) mới và cd vào thư mục chứa đồ án
Kill toàn bộ python và port còn dư: taskkill /F /IM python.exe
Dọn dữ liệu/logs:
  Remove-Item -Recurse -Force .\data
  Remove-Item node-*.log -Force
  Remove-Item -Recurse -Force .\artifacts
  New-Item -ItemType Directory -Path data,artifacts
(Nếu xài CMD thì chạy lệnh: rmdir /S /Q logs rmdir /S /Q artifacts mkdir logs mkdir artifacts)
Kích hoạt môi trường: .venv\Scripts\activate
Chạy FULL TEST (lần 1) python -m pytest -q
Kill python lần nữa taskkill /F /IM python.exe
Dọn sạch lại dữ liệu/logs:
  Remove-Item -Recurse -Force .\data
  Remove-Item node-*.log -Force
  Remove-Item -Recurse -Force .\artifacts
  New-Item -ItemType Directory -Path data,artifacts
(Nếu xài CMD thì chạy lệnh: rmdir /S /Q logs rmdir /S /Q artifacts mkdir logs mkdir artifacts)
Chạy DURABILITY (lần 2)
python -m pytest tests/test_durability.py::test_durability -q
Test pBFT:
python start_pbft_cluster.py 
pytest -q test_pbft.py
Khi test thất bại, kiểm tra artifacts/ và node-*.log để phân tích.


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