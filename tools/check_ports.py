"""
Check required cluster ports are free on localhost. Exits 0 if free, non-zero if any in-use.
"""
import socket
import sys

# ports used by cluster nodes (gRPC) and status HTTP (gRPC+1000)
GRPC_BASE_PORTS = [5001, 5002, 5003, 5004, 5005]
STATUS_BASE_PORTS = [p + 1000 for p in GRPC_BASE_PORTS]

ports = GRPC_BASE_PORTS + STATUS_BASE_PORTS

in_use = []
for port in ports:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.1)
    try:
        s.bind(('127.0.0.1', port))
    except Exception:
        in_use.append(port)
    finally:
        try:
            s.close()
        except Exception:
            pass

if in_use:
    print('ERROR: The following required ports are in use:', in_use)
    print('Please stop conflicting processes before running the durability test in CI.')
    sys.exit(2)
else:
    print('All required ports are free. Proceeding.')
    sys.exit(0)
