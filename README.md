# Lab01Blockchain

## Hướng dẫn sử dụng (Tiếng Việt)


1️⃣ Vào thư mục
cd C:\Users\ADMIN\Documents\GitHub\texta\Lab01Blockchain

2️⃣ Kill toàn bộ python + port
taskkill /F /IM python.exe

3️⃣ Dọn sạch dữ liệu
rmdir /S /Q logs
rmdir /S /Q artifacts
mkdir logs
mkdir artifacts

4️⃣ Active venv
.venv\Scripts\activate

5️⃣ Chạy FULL TEST (lần 1)
python -m pytest -q

6️⃣ Kill python lần nữa
taskkill /F /IM python.exe

7️⃣ Dọn sạch lại
rmdir /S /Q logs
rmdir /S /Q artifacts
mkdir logs
mkdir artifacts

8️⃣ Chạy DURABILITY (lần 2)
python -m pytest tests/test_durability.py::test_durability -q

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
