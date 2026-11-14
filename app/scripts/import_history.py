"""Root wrapper for app.scripts.import_history."""
import os
import sys
import runpy

server_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "server"))
# Remove any root 'app' from sys.modules so server/app is loaded
sys.modules.pop("app", None)
sys.modules.pop("app.scripts", None)
sys.modules.pop("app.scripts.import_history", None)
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

target_script = os.path.join(server_dir, "app", "scripts", "import_history.py")

if __name__ == "__main__":
    runpy.run_path(target_script, run_name="__main__")
