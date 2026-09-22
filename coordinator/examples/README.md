# Offline examples

These records are **synthetic fixtures**, not TYK2 findings or benchmark evidence.

- `missing-evidence.json`: all four requested biological contexts/assays lack
  observations. Expected: `partial`, `not_assessable`.
- `cross-context-conflict.json`: synthetic cultured human-cell RNA, mouse in-vivo
  RNA, and paired human-patient RNA/protein. The mouse direction opposes the others.
  Expected: `complete`, `conflicting`. Context/species/normalization bases are declared
  synthetic examples, not independently validated mappings.
- `packages/TYK2.json`: replay-only pipeline-shaped package, with explicit skipped
  live sources. No source is contacted when `XCTX_EVIDENCE_DIR` points here.

Run from the repository root after installing coordinator dependencies:

```bash
XCTX_EVIDENCE_DIR="$PWD/coordinator/examples/packages" \
XCTX_RUN_DIR=/tmp/xctx-demo-runs \
python -m coordinator.cli coordinator/examples/missing-evidence.json

XCTX_EVIDENCE_DIR="$PWD/coordinator/examples/packages" \
XCTX_RUN_DIR=/tmp/xctx-demo-runs \
python -m coordinator.cli coordinator/examples/cross-context-conflict.json
```

Both inputs supply explicit criteria, so no Claude key or model call is needed.
Run JSON, including evidence, gaps and the Markdown report, is saved in the chosen
run directory. Exit code 0 means execution returned a complete **or partial** report;
always inspect its status and scientific conclusion. Exit code 1 means failure.
