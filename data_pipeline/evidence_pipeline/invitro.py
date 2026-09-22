"""In-vitro context enrichment (v3 §1 in vitro branch).

Adds cell-line evidence to an existing per-gene package WITHOUT modifying
`package.build_package`. Called from `build_one` (Modal wrapper) so both the
per-gene and pathway runs get the in-vitro context in a single pass.

Sources (both background, result_origin=published_retrieved, leaks_answers=False,
so they run in eval mode too):
  hpa_cell_lines     - HPA cell-line RNA + protein
  opentargets_depmap - DepMap CRISPR fitness essentiality
"""
from __future__ import annotations

import sources as S

INVITRO_SOURCES = ["hpa_cell_lines", "opentargets_depmap"]


def enrich_invitro(pkg: dict, mode: str, cache) -> dict:
    """Attach in-vitro sources to a per-gene package (mutates and returns it).

    In-vitro sources do not leak benchmark answers, so they are queried in every
    mode. Cached like any other source (ok/not_found only).
    """
    ensg = (pkg.get("gene", {}).get("data") or {}).get("ensembl_primary")
    for name, fn in [("hpa_cell_lines", lambda: S.hpa_cell_lines(ensg)),
                     ("opentargets_depmap", lambda: S.opentargets_depmap(ensg))]:
        if not ensg:
            pkg["sources"][name] = S.result(name, "skipped", {},
                                            error="no ensembl id (gene normalization failed)")
        else:
            pkg["sources"][name] = cache.fetch(name, {"ensg": ensg}, fn)
    # keep `missing` consistent with the added sources
    for name in INVITRO_SOURCES:
        r = pkg["sources"][name]
        if r["status"] != "ok":
            pkg["missing"].append({"source": name, "sub": None,
                                   "status": r["status"], "reason": r.get("error")})
    return pkg
