# Investigation coordinator: approved design and implementation handoff

Base: `jaeeun-wittgen/data-pipeline` at `42794d812772c9b0c15a4b2cb5f4a07df36060e3`.
Working branch: `codex/investigation-coordinator`.

The user approved one coordinator serving the frontend, with evidence collection
reused from the data branch. MCP is owned by a separate session. Frontend development
and whole-system evaluation are also separate workstreams.

## Intent and scope

Help a computational biology researcher investigate whether a specified observation
has supporting or conflicting evidence across species, experimental situations and
modalities. Keep in-vitro, in-vivo and patient contexts explicit. Preserve patient,
specimen and timepoint identity for claims about the same person. Treat tissue,
condition, measured species and host species as separate fields.

The implementation is a structural evidence-checking MVP. It does not compute pathway
activity, validate experimental designs, infer causal mechanisms, or perform meta-analysis.
The current collection branch supplies background knowledge. A complete descriptive
comparison also needs normalized observations with provenance supplied through the
input contract; the included observations are conspicuously synthetic demo data.

## Executable boundaries

1. **Intent and success definition:** `Planner.plan(request) -> ResearchPlan` runs
   before evidence collection. Explicit criteria need no model. Free text uses one
   configured Claude call, validated against the same schema. Preserve explicit
   species/context/modality requirements; mark inferred choices as assumptions.
2. **Frozen plan and feasibility:** store the plan and its SHA-256 digest. Each
   requirement names a concrete entity, species, context, modality and endpoint.
   Missing inputs remain unmet requirements. A supplied versioned pathway membership
   can fan out gene collection but does not create a pathway-activity observation.
3. **Collection:** read the full JSON behind the data pipeline's Modal receipt;
   validate gene, query and run identity. Keep source status and raw packages.
4. **Comparison and checks:** require qualified observation records and traceable
   source/study identity; count distinct study IDs. Check endpoints, contrasts,
   comparison keys, alignment declarations, and patient pairing. These are structural
   checks of declared metadata, not independent validation of the declarations.
5. **Bounded follow-up:** at most one technical collection retry per gene, under
   a between-step time budget. Never weaken criteria or seek a positive result by
   changing an analysis. Unavailable biological observations require additional data.
6. **Outcome:** execution is complete/partial/failed, independently of the descriptive
   supported/conflicting/inconclusive/not_assessable conclusion. A valid conflict
   can complete the investigation. A partial investigation lists what is missing.

The plan and verification procedure are adapted in our own words from
[AutoSciRub, pinned source](https://github.com/zjunlp/AutoSciRub/tree/333a9e5b7e405f54aca2e74d9c4f58aeece96332).
We use its intent-before-evidence and fixed-rubric revision pattern, not its whole
runtime. The host-side skills are not a drop-in numerical biology validator.
No upstream implementation code is vendored in this change.

## Work packages and dependency order

| Work package | Files | Inputs and outputs | Status in this branch |
|---|---|---|---|
| Shared contracts | `coordinator/models.py` | Request, plan, observation, assessment, run | Implemented |
| Planner | `planner.py`, `prompts/intent.md` | Request → validated plan | Implemented; provider calls mocked in tests |
| Evidence integration | `evidence.py` | Modal receipt or local package → evidence bundle | Implemented; live cloud verification pending |
| Scientific gates | `checks.py` | Fixed plan + bundle → assessment | Implemented; structural checks only |
| Controller and storage | `engine.py`, `store.py`, `jobs.py` | Bounded run with persisted progress | Implemented |
| HTTP and deployment | `api.py`, `modal_app.py`, `runtime.py` | Start, poll, report | Local contract tested; cloud deployment pending |
| Integration examples | `examples/` | Missing-data and conflicting-observation cases | Synthetic, offline, runnable |
| Frontend / independent evaluation | Other sessions | Consume API and exported run JSON | Separate ownership |

## Verification and acceptance

- Test real failure boundaries: malformed receipts, inconsistent queries, empty
  criteria, source success mistaken for observations, duplicate study counts,
  unpaired patients, unmatched biological conditions, and frozen criteria mutation.
- Run both synthetic examples end to end: missing observations → partial;
  fully supplied but opposing comparable directions → complete + conflicting.
- Exercise POST → polling → report, invalid requests, dispatch failure and a
  terminated cloud worker through fake provider/worker handles.
- Run the existing data-pipeline tests to protect the inherited contract.
- Make no benchmark superiority claim from these implementation tests. The separate
  evaluation workstream owns the 10–20 minute comparison against an ordinary agent.

## Remaining integration work

The frontend can use the documented API immediately with offline examples. The live
team deployment needs its configured Claude model/key, coordinator token, existing
`xctx-evidence` deployment and Modal access. One live package retrieval and one live
provider plan are still needed to verify those external integrations. A scientific
data owner must provide and review observation normalization before the system can
make useful biological comparisons beyond the synthetic examples.
