from tools.fault_tests import probe_states
import json

s = probe_states()
print(json.dumps(s, indent=2))
