import json
from pathlib import Path
from comfy_runner.config import CONFIG_FILE, load_config

print(f"Config file: {CONFIG_FILE}")
print(f"Exists: {CONFIG_FILE.exists()}")

# Read raw file directly
raw = CONFIG_FILE.read_text(encoding="utf-8")
direct = json.loads(raw)
print(f"Direct read keys: {list(direct.keys())}")
print(f"Direct has github_token: {'github_token' in direct}")

# Check .bak file
bak = Path(str(CONFIG_FILE) + ".bak")
print(f"Bak exists: {bak.exists()}")
if bak.exists():
    bak_data = json.loads(bak.read_text(encoding="utf-8"))
    print(f"Bak keys: {list(bak_data.keys())}")

# Check via atomic_read
from safe_file import atomic_read
ar = atomic_read(CONFIG_FILE)
if ar:
    ar_data = json.loads(ar)
    print(f"atomic_read keys: {list(ar_data.keys())}")
else:
    print("atomic_read returned None")
