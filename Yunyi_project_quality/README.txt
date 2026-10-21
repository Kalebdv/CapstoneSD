ComfyUI Project Quality metrics (Final report, Step 2: M1-M6)
=============================================================

Pinned ComfyUI snapshot : c194dd00cd42aa18d9dbf27d977bf6b85d9ea565 (authored 2026-09-20)
Measured on             : 2026-10-20
Tools (pinned)          : radon 6.0.1, ruff 0.14.0, lizard 1.17.31, bandit 1.8.6

These scripts reproduce every number in the "Project Quality" section's metric
table. All measurements are static (no code is executed), so no GPU, model
weights or ComfyUI runtime are needed -- only a checkout of ComfyUI at the pinned
commit and the four analysis tools above.

Measurement scope ("core")
---------------------------
Hand-written product code only. Packages:
  comfy, comfy_execution, comfy_api, comfy_api_nodes, comfy_config,
  comfy_extras, app, api_server, middleware, utils
plus the top-level entry points:
  main.py, nodes.py, execution.py, server.py, folder_paths.py,
  node_helpers.py, latent_preview.py, cuda_malloc.py
Excluded: tests/ and tests-unit/ (measured separately for M5), CI scaffolding,
and report sources. The scope is encoded in CORE_DIRS / CORE_FILES in
run_metrics.py so it is explicit and auditable.

Metrics
-------
  M1  Cyclomatic complexity        radon cc   -> Analysability/Modifiability/Testability
  M2  Maintainability Index        radon mi   -> Analysability/Modifiability
  M3  Module size (SLOC)           radon raw  -> Modularity/Analysability
  M4  Lint / code-smell density    ruff       -> Analysability/Modifiability
  M5  Test density                 grep+radon -> Testability (+ Reliability-Maturity)
  M6  Security static scan         bandit     -> Security-Integrity
lizard is used only as an independent cross-check of M1.

Usage
-----
  # 1. Get ComfyUI at the pinned commit
  git clone https://github.com/Comfy-Org/ComfyUI.git
  git -C ComfyUI checkout c194dd00cd42aa18d9dbf27d977bf6b85d9ea565

  # 2. Install the pinned tools into an isolated venv (recommended)
  python3 -m venv .venv
  ./.venv/bin/pip install -r requirements.txt

  # 3. Run
  python3 run_metrics.py --comfyui ./ComfyUI --bin-dir ./.venv/bin --out output

Outputs
-------
  output/metrics.json   full machine-readable results (grade distributions,
                        grade-C file list, largest files, bandit High/Medium
                        locations, etc.)
  stdout                a one-line-per-metric summary matching the report table.

Notes on definitions (so the numbers are unambiguous)
-----------------------------------------------------
  - M3 comment ratio is single-line '#' comments over physical LOC (radon's
    C%L), i.e. ~4%.
  - M4 reports three counts: findings under ComfyUI's own ruff config (0, since
    CI gates it), findings under a broad isolated ruleset
    (E,F,W,B,SIM,C90,PERF,RUF,UP), and that broad count minus E501 line-length
    (the smells the project does not currently gate). "bugbear_B" is the
    likely-bug subset (ruff rule class B).
  - M5 uses test density as a static proxy because line/branch coverage cannot
    be produced here without a full GPU runtime and model weights.

The scripts are read-only: they never write to GitHub and never modify the
ComfyUI checkout.
