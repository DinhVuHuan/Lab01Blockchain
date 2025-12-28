import urllib.request
addrs={1:'127.0.0.1:5001',2:'127.0.0.1:5002',3:'127.0.0.1:5003',4:'127.0.0.1:5004',5:'127.0.0.1:5005'}
for nid, addr in addrs.items():
    host, port = addr.split(':')
    url = f'http://{host}:{int(port)+1000}/state'
    try:
        with urllib.request.urlopen(url, timeout=0.5) as r:
            print(nid, r.read().decode())
    except Exception as e:
        print(nid, 'error', e)
