"""Internal worker entry point, separate from the public CLI."""
from pathlib import Path
import sys

from .jobs import run_worker

if __name__ == "__main__":
    try:
        raise SystemExit(run_worker(Path(sys.argv[1]), sys.argv[2]))
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Worker failed: {error}", file=sys.stderr)
        raise SystemExit(1)
