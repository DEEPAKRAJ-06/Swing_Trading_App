from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloud_app.workflow import run_daily_workflow


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["fast", "standard", "full"], default="fast")
    args = parser.parse_args()
    result = run_daily_workflow(mode=args.mode)
    print(json.dumps({"status": "completed", "run_id": result["run_id"], "scan": result["scan"]}, indent=2, default=str))


if __name__ == "__main__":
    main()

