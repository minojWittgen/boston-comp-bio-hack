"""Integration layer: connects the PRODUCTION data pipeline and coordinator to the benchmark corpus.

Nothing in data_pipeline/ or coordinator/ is modified. This package only:
  * replays recorded native API responses into the pipeline's own `sources.http` (runtime patch, per run),
  * runs the pipeline's real build_package → enrich_invitro → annotate_package path,
  * provides the system's extraction/normalization stage over the corpus (LLM-assisted, provenance-linked),
  * drives the real Coordinator (planner → frozen plan → collection → checks → report),
  * maps the RunState into the benchmark's public report envelope without adding evidence.
"""
