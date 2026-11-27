"""Run the source-checkout unittest suite, including child Python processes."""
import os
from pathlib import Path
import subprocess
import sys


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    paths = [str(root / "bridge"), str(root)]
    if os.environ.get("PYTHONPATH"):
        paths.append(os.environ["PYTHONPATH"])
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(paths)}
    arguments = sys.argv[1:] or ["discover", "-s", "tests", "-v"]
    sys.exit(subprocess.call([sys.executable, "-B", "-m", "unittest", *arguments],
                             cwd=root, env=environment))
