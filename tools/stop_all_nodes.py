from tools import admin
import config

for nid in config.NODES.keys():
    print(f"Shutting down node {nid}:", admin.shutdown(nid))
