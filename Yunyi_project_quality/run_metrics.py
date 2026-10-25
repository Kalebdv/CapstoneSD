#!/usr/bin/env python3
"""Reproduce the Project Quality metrics (M1-M6) for ComfyUI.

This script re-runs every measurement reported in the Project Quality section
(Step 2) against a ComfyUI checkout and writes the results to output/metrics.json
plus a human-readable summary. It shells out to pinned static-analysis tools
(see requirements.txt) and parses their JSON output so the numbers are exact and
reproducible.

Provenance of the numbers in the report:
  ComfyUI commit : c194dd00cd42aa18d9dbf27d977bf6b85d9ea565 (authored 2026-09-20)
  Measured on    : 2026-10-20
  Tools          : radon 6.0.1, ruff 0.14.0, lizard 1.17.31, bandit 1.8.6
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Core source scope: hand-written product code only. Excludes the test suites
# (measured separately in M5), CI scaffolding and report sources.
CORE_DIRS = [
    "comfy", "comfy_execution", "comfy_api", "comfy_api_nodes",
    "comfy_config", "comfy_extras", "app", "api_server", "middleware", "utils",
]
CORE_FILES = [
    "main.py", "nodes.py", "execution.py", "server.py", "folder_paths.py",
    "node_helpers.py", "latent_preview.py", "cuda_malloc.py",
]
TEST_DIRS = ["tests", "tests-unit"]

RUFF_BROAD_SELECT = "E,F,W,B,SIM,C90,PERF,RUF,UP"


def tool(bin_dir: str | None, name: str) -> str:
    """Resolve a tool, preferring an explicit --bin-dir (e.g. a venv's bin)."""
    if bin_dir:
        cand = Path(bin_dir) / name
        if cand.exists():
            return str(cand)
    found = shutil.which(name)
    if not found:
        sys.exit(f"ERROR: tool '{name}' not found. Install requirements.txt "
                 f"(optionally into a venv) and pass --bin-dir <venv>/bin.")
    return found


def run_json(cmd: list[str]) -> object:
    """Run a command that prints JSON on stdout and parse it (tolerant of exit code)."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = proc.stdout.strip()
    if not out:
        sys.exit(f"ERROR: no output from: {' '.join(cmd)}\n{proc.stderr[:500]}")
    return json.loads(out)


def core_targets(root: Path) -> list[str]:
    targets = []
    for d in CORE_DIRS + CORE_FILES:
        p = root / d
        if p.exists():
            targets.append(str(p))
    return targets


def m1_complexity(radon: str, targets: list[str]) -> dict:
    data = run_json([radon, "cc", "-j", *targets])
    grades: dict[str, int] = {g: 0 for g in "ABCDEF"}
    total, csum, worst = 0, 0, []
    for blocks in data.values():
        for b in blocks:
            if not isinstance(b, dict) or "rank" not in b:
                continue
            grades[b["rank"]] += 1
            total += 1
            csum += b["complexity"]
            worst.append((b["complexity"], b.get("name", "?")))
    worst.sort(reverse=True)
    df = grades["D"] + grades["E"] + grades["F"]
    return {
        "blocks": total,
        "mean_cc": round(csum / total, 2) if total else 0,
        "grades": grades,
        "blocks_D_to_F": df,
        "pct_D_to_F": round(100 * df / total, 2) if total else 0,
        "worst5": worst[:5],
    }


def m2_mi(radon: str, targets: list[str]) -> dict:
    data = run_json([radon, "mi", "-j", *targets])
    ranks = {"A": 0, "B": 0, "C": 0}
    c_files = []
    for path, info in data.items():
        if not isinstance(info, dict) or "rank" not in info:
            continue
        ranks[info["rank"]] += 1
        if info["rank"] == "C":
            c_files.append(path)
    total = sum(ranks.values())
    return {
        "files": total,
        "ranks": ranks,
        "pct_A": round(100 * ranks["A"] / total, 1) if total else 0,
        "pct_C": round(100 * ranks["C"] / total, 1) if total else 0,
        "grade_C_files": sorted(c_files),
    }


def m3_size(radon: str, targets: list[str]) -> dict:
    data = run_json([radon, "raw", "-j", *targets])
    total_sloc = total_loc = total_comments = 0
    per_file = []
    for path, info in data.items():
        if not isinstance(info, dict) or "sloc" not in info:
            continue
        total_sloc += info["sloc"]
        total_loc += info.get("loc", 0)
        total_comments += info.get("comments", 0)  # single-line '#' comments (radon C%L)
        per_file.append((info["sloc"], path))
    per_file.sort(reverse=True)
    return {
        "core_sloc": total_sloc,
        "comment_ratio_pct": round(100 * total_comments / total_loc, 1) if total_loc else 0,
        "files_over_2500_sloc": sum(1 for s, _ in per_file if s > 2500),
        "largest10": per_file[:10],
    }


def m4_lint(ruff: str, root: Path, targets: list[str]) -> dict:
    def count(extra: list[str]) -> list[dict]:
        cmd = [ruff, "check", *targets, "--output-format", "json", *extra]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=root)
        try:
            return json.loads(proc.stdout or "[]")
        except json.JSONDecodeError:
            return []

    repo_gate = count([])  # uses the repo's own pyproject.toml ruff config
    broad = count(["--isolated", "--select", RUFF_BROAD_SELECT])
    broad_no_e501 = [f for f in broad if f.get("code") != "E501"]
    bugbear = [f for f in broad if (f.get("code") or "").startswith("B")]
    return {
        "repo_gate_findings": len(repo_gate),
        "broad_findings": len(broad),
        "broad_excl_E501": len(broad_no_e501),
        "bugbear_B": len(bugbear),
    }


def m5_tests(radon: str, root: Path) -> dict:
    test_targets = [str(root / d) for d in TEST_DIRS if (root / d).exists()]
    n_files = sum(1 for d in test_targets for _ in Path(d).rglob("*.py"))
    pat = re.compile(r"def\s+test_[A-Za-z0-9_]+")
    n_funcs = 0
    for d in test_targets:
        for f in Path(d).rglob("*.py"):
            n_funcs += len(pat.findall(f.read_text(errors="ignore")))
    data = run_json([radon, "raw", "-j", *test_targets]) if test_targets else {}
    test_sloc = sum(v["sloc"] for v in data.values()
                    if isinstance(v, dict) and "sloc" in v)
    return {"test_files": n_files, "test_functions": n_funcs, "test_sloc": test_sloc}


def m6_security(bandit: str, targets: list[str]) -> dict:
    cmd = [bandit, "-r", *targets, "-f", "json", "-q"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        sys.exit(f"ERROR: bandit produced no JSON\n{proc.stderr[:500]}")
    sev = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    top = []
    for r in data.get("results", []):
        sev[r["issue_severity"]] = sev.get(r["issue_severity"], 0) + 1
        if r["issue_severity"] in ("HIGH", "MEDIUM"):
            top.append(f'{r["issue_severity"]} {r["test_id"]} {r["filename"]}:{r["line_number"]}')
    return {"severity": sev, "high_medium": top}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--comfyui", required=True, help="path to a ComfyUI checkout")
    ap.add_argument("--bin-dir", default=None,
                    help="dir holding the installed tools (e.g. <venv>/bin)")
    ap.add_argument("--out", default="output")
    args = ap.parse_args()

    root = Path(args.comfyui).resolve()
    if not root.exists():
        sys.exit(f"ERROR: ComfyUI path not found: {root}")
    radon = tool(args.bin_dir, "radon")
    ruff = tool(args.bin_dir, "ruff")
    bandit = tool(args.bin_dir, "bandit")
    targets = core_targets(root)

    commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout.strip()

    results = {
        "comfyui_path": str(root),
        "commit": commit,
        "core_scope": CORE_DIRS + CORE_FILES,
        "M1_cyclomatic_complexity": m1_complexity(radon, targets),
        "M2_maintainability_index": m2_mi(radon, targets),
        "M3_module_size": m3_size(radon, targets),
        "M4_lint_density": m4_lint(ruff, root, targets),
        "M5_test_density": m5_tests(radon, root),
        "M6_security_scan": m6_security(bandit, targets),
    }

    outdir = Path(args.out).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "metrics.json").write_text(json.dumps(results, indent=2))

    m1, m2, m3 = results["M1_cyclomatic_complexity"], results["M2_maintainability_index"], results["M3_module_size"]
    m4, m5, m6 = results["M4_lint_density"], results["M5_test_density"], results["M6_security_scan"]
    sloc_k = m3["core_sloc"] / 1000
    print("\n==== Project Quality metrics ====")
    print(f"commit {commit[:12]}")
    print(f"M1 CC   : {m1['blocks']} blocks, mean {m1['mean_cc']} (A); "
          f"grades {m1['grades']}; D-F {m1['blocks_D_to_F']} ({m1['pct_D_to_F']}%)")
    print(f"M2 MI   : {m2['files']} files; A {m2['ranks']['A']} ({m2['pct_A']}%), "
          f"B {m2['ranks']['B']}, C {m2['ranks']['C']} ({m2['pct_C']}%)")
    print(f"M3 size : {m3['core_sloc']} SLOC, comments {m3['comment_ratio_pct']}%, "
          f"{m3['files_over_2500_sloc']} files >2500 SLOC")
    print(f"M4 lint : repo-gate {m4['repo_gate_findings']}; broad {m4['broad_findings']}; "
          f"excl-E501 {m4['broad_excl_E501']} (~{m4['broad_excl_E501']/sloc_k:.1f}/KLoC); "
          f"bugbear-B {m4['bugbear_B']}")
    print(f"M5 test : {m5['test_files']} files, {m5['test_functions']} funcs, "
          f"{m5['test_sloc']} SLOC; test:core ratio {m5['test_sloc']/m3['core_sloc']:.3f}")
    print(f"M6 sec  : High {m6['severity']['HIGH']}, Medium {m6['severity']['MEDIUM']}, "
          f"Low {m6['severity']['LOW']}")
    print(f"\nwrote {outdir / 'metrics.json'}")


if __name__ == "__main__":
    main()
