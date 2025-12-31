# Lab01Blockchain

# 1. Tổng quan
Dự án này mô phỏng một cụm RAFT 5 node (mỗi node chạy riêng một process) dùng **gRPC** để trao đổi RPC. Mục tiêu: triển khai leader election, log replication, commit bằng đa số và kiểm tra tính bền vững (durability) khi restart.

# 2. Yêu cầu & chuẩn bị môi trường (Windows)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install grpcio grpcio-tools pytest

### Dọn dữ liệu/logs
Remove-Item -Recurse -Force .\data
Remove-Item node-*.log -Force
Remove-Item -Recurse -Force .\artifacts
New-Item -ItemType Directory -Path data,artifacts

 Nếu xài CMD:
rmdir /S /Q logs
rmdir /S /Q artifacts
mkdir logs
mkdir artifacts

### 2. Kiểm tra port
python tools/check_ports.py
taskkill /PID <pid> /F  # kill port bị chiếm
 start_cluster.py --force để bỏ preflight port check (debug local)

### 3. Start node và cluster
python start_node.py 1            # start 1 node
python start_cluster.py            # start toàn bộ cluster 5 node
python start_cluster.py --force    # bỏ preflight port check
python run_node.py                 # chạy nhiều node trong cùng process (dev)
python tools/stop_all_nodes.py     # dừng tất cả node

### 4. Kiểm tra trạng thái node & admin endpoints (HTTP)
Invoke-RestMethod "http://127.0.0.1:6001/state"
Invoke-RestMethod "http://127.0.0.1:6001/admin/disconnect?peers=2,3"
Invoke-RestMethod "http://127.0.0.1:6001/admin/reconnect?peers=2,3"
Invoke-RestMethod "http://127.0.0.1:6001/admin/shutdown"

### 5. Gửi lệnh từ client
python raft_client.py set mykey 123
python raft_cilent.py set mykey 123  # support tên file cũ

### 6. Thay đổi số node / ports / topology
 -> sửa file config.py (NODES dict), kiểm tra port, restart cluster

### 7. Mô phỏng lỗi / Byzantine
 - Partition / blackhole: /admin/disconnect
 - Shutdown node: /admin/shutdown hoặc kill PID
 - Ép term: /admin/setterm?term=NN
 - pBFT demo: run_pbft_node.py (byzantine=(i==3))

### 8. Persistence & durability
python -m pytest tests/test_durability.py::test_durability -q

### 9. File log & artifacts
 node-1.log, node-2.log, ... 
 artifacts/<timestamp>_reason/ (dump_logs helper)

# 3. Các bước chạy step-by-step
 Mở PowerShell, di chuyển vào thư mục project
 Tạo & kích hoạt venv
 Kiểm tra port
python tools/check_ports.py

### Khởi cụm 5 node
python start_cluster.py

Hoặc start 1 node debug
python start_node.py 1

Xác minh trạng thái node
Invoke-RestMethod "http://127.0.0.1:6001/state"

Gửi lệnh ví dụ
python raft_client.py set example 100

Mô phỏng fault
 - tắt leader: /admin/shutdown
 - blackhole follower: /admin/disconnect

Chạy test tổng quát, durability, pBFT
taskkill /F /IM python.exe
Remove-Item -Recurse -Force .\data
Remove-Item node-*.log -Force
Remove-Item -Recurse -Force .\artifacts
New-Item -ItemType Directory -Path data,artifacts
.venv\Scripts\activate

FULL TEST (lần 1)
python -m pytest -q

Kill python lần nữa
taskkill /F /IM python.exe

Dọn sạch dữ liệu/logs
Remove-Item -Recurse -Force .\data
Remove-Item node-*.log -Force
Remove-Item -Recurse -Force .\artifacts
New-Item -ItemType Directory -Path data,artifacts

Chạy DURABILITY (lần 2)
python -m pytest tests/test_durability.py::test_durability -q

Test pBFT
python start_pbft_cluster.py
pytest -q test_pbft.py

Khi test thất bại, kiểm tra artifacts/ và node-*.log để phân tích

### 4. Cấu trúc thư mục

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