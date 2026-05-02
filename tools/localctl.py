#!/usr/bin/env python3
from __future__ import annotations

import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "scripts" / "utils" / "localctl.py"


if __name__ == "__main__":
    runpy.run_path(str(TARGET), run_name="__main__")
