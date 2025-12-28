"""Admin helpers to call /admin endpoints on nodes."""
import urllib.request
import urllib.error
import config


def _call(addr, path):
    host, port = addr.split(":")
    url = f"http://{host}:{int(port)+1000}{path}"
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.read().decode()
    except Exception as e:
        return str(e)


def disconnect(node_id, peers):
    addr = config.NODES[node_id]
    peers_str = ','.join(str(x) for x in peers)
    return _call(addr, f'/admin/disconnect?peers={peers_str}')


def reconnect(node_id, peers):
    addr = config.NODES[node_id]
    peers_str = ','.join(str(x) for x in peers)
    return _call(addr, f'/admin/reconnect?peers={peers_str}')


def clear(node_id):
    addr = config.NODES[node_id]
    return _call(addr, '/admin/clear')


def shutdown(node_id):
    addr = config.NODES[node_id]
    return _call(addr, '/admin/shutdown')


def setterm(node_id, term):
    addr = config.NODES[node_id]
    return _call(addr, f'/admin/setterm?term={term}')


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        print('Usage: admin.py <cmd> <node> [args]')
        print('cmd: disconnect,reconnect,clear,shutdown,setterm')
        sys.exit(1)
    cmd = sys.argv[1]
    nid = int(sys.argv[2])
    if cmd == 'disconnect':
        peers = [int(x) for x in sys.argv[3].split(',')]
        print(disconnect(nid, peers))
    elif cmd == 'reconnect':
        peers = [int(x) for x in sys.argv[3].split(',')]
        print(reconnect(nid, peers))
    elif cmd == 'clear':
        print(clear(nid))
    elif cmd == 'shutdown':
        print(shutdown(nid))
    elif cmd == 'setterm':
        t = int(sys.argv[3])
        print(setterm(nid, t))
    else:
        print('Unknown cmd')
