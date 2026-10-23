# Local ComfyUI quality-improvement demonstration

This directory contains code, tests and reproducible measurements for a small
demonstration against ComfyUI commit
`c194dd00cd42aa18d9dbf27d977bf6b85d9ea565`. It does not contain report text or UML.

## Implemented changes

1. Extract the MMDiT and Stable Cascade configuration-building branches from
   `detect_unet_config` into two private functions in the same module, preserving
   the original conditions and their order.
2. Replace the read-only `any_suffix_in` default argument `[]` with `()`.
   The original function does not mutate that list, so this is preventive
   cleanup, not a demonstrated fix for an existing state-sharing failure.

No node-loading architecture changes or security changes are implemented here.

## Contents

- `improvement.patch`: applicable diff against the pinned ComfyUI source.
- `before/comfy/model_detection.py`: original source snapshot.
- `after/comfy/model_detection.py`: modified source snapshot.
- `reproduce.py`: rebuild both snapshots and the patch, run tests, and measure.
- `test_quality_demo.py`: six focused characterization test methods.
- `requirements.txt`: pinned static-analysis dependencies.
- `measurement.json`: measurement environment, versions, timestamp, results and
  SHA-256 hashes of the before/after files.
- `test_results.txt`: recorded unittest output.
- `ComfyUI_LICENSE`: license accompanying the upstream source snapshots.

## Reproduce

Use Python 3.12.6 to match the recorded run. A virtual environment is recommended.
From this directory, run:

```sh
python -m pip install -r requirements.txt
git clone https://github.com/Comfy-Org/ComfyUI.git ComfyUI
git -C ComfyUI checkout c194dd00cd42aa18d9dbf27d977bf6b85d9ea565
python reproduce.py --source ComfyUI
```

An existing checkout at that revision can be passed instead. The script reads
the pinned file with `git show`, without modifying the source checkout. It
regenerates the snapshots, patch, test log and measurement JSON in this directory.
Rerunning changes the recorded timestamp and test duration.

To rerun only the supplied tests after the snapshots exist:

```sh
python -m unittest -v test_quality_demo
```

To inspect and apply the change in a separate ComfyUI checkout, run from its root:

```sh
git apply --check /path/to/Christina/improvement.patch
git apply /path/to/Christina/improvement.patch
```

## Recorded local results

The measurement scope is the complete `comfy/model_detection.py` file or the
explicitly named functions. These are not recomputed repository-wide M1--M6 totals.

| Indicator | Before | After |
| --- | ---: | ---: |
| Dispatcher cyclomatic complexity | 217 | 202 |
| Extracted MMDiT helper complexity | n/a | 10 |
| Extracted Cascade helper complexity | n/a | 7 |
| Whole-module Maintainability Index | 0.0 | 0.0 |
| Whole-module SLOC | 1415 | 1419 |
| Whole-module Ruff B006 findings | 1 | 0 |

The dispatcher remains highly complex. Summing the new function complexities
gives 219 rather than 217 because each function has a base complexity of one.
After subtracting those bases, the number of decisions remains 216. This is a
redistribution of responsibilities, not elimination of decisions.

## Tests and limitations

Six test methods pass, including 256 MMDiT combinations, 16 Cascade cases and
two cross-family precedence cases. Additional checks cover missing-key error
preservation, suffix matching and AST equality of the remaining dispatcher.
Differential cases compare original and modified results and check that the
inputs are not mutated.

The harness compiles selected function bodies from the actual source snapshots,
supplies `math`, and uses objects exposing only tensor shapes. It skips the
heavyweight application imports. It does not run GPU inference, import the full
application, measure branch coverage, benchmark performance or validate all model
families. Passing these tests is local characterization evidence, not a claim
that the patch is ready for an upstream production release.

Source: [pinned upstream module](https://github.com/Comfy-Org/ComfyUI/blob/c194dd00cd42aa18d9dbf27d977bf6b85d9ea565/comfy/model_detection.py).
