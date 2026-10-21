#!/usr/bin/env python3
"""Run the complete project-health data pipeline in order."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output")
    args = ap.parse_args()
    root = Path(__file__).resolve().parent
    out = Path(args.out).resolve()
    commands = [
        [sys.executable, str(root / "01_collect_activity.py"), "--out", str(out)],
        [sys.executable, str(root / "02_analyze_contributors.py"), "--data", str(out)],
        [sys.executable, str(root / "03_sample_artifacts.py"), "--data", str(out)],
    ]
    for cmd in commands:
        print("+", " ".join(cmd), flush=True)
        subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
