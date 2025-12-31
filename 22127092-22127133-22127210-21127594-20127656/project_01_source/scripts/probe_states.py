from tools.fault_tests import probe_states
import json

print(json.dumps(probe_states(), indent=2, ensure_ascii=False))
