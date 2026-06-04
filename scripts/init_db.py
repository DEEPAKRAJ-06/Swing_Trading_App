from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloud_app.db import initialize_database


if __name__ == "__main__":
    initialize_database()
    print("Cloud database initialized.")

