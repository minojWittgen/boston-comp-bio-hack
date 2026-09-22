# Boston Computational Biology Hackathon — Team Workspace

Shared code and notes for our team's project at the [Boston Computational Biology Hackathon](https://luma.com/boston-comp-bio-hack), hosted by Anthropic, Modal, and Flagship Pioneering.

## Get started

```bash
git clone https://github.com/minojWittgen/boston-comp-bio-hack.git
cd boston-comp-bio-hack
git switch -c your-name/short-task
```

The project idea and application stack are still to be decided. Setup and run instructions will go here once the team selects them.

## Repository layout

| Path | What it holds |
|---|---|
| [`cross-context-biology-agent.md`](cross-context-biology-agent.md) | The design document — architecture, evidence dimensions, and the criteria the agent is judged against. |
| [`data_pipeline/`](data_pipeline/README.md) | Retrieval layer. Turns a gene or pathway into a deterministic, context-tagged evidence package. Makes no judgments and computes no scores. |
| [`benchmarking/`](benchmarking/README.md) | Evaluation layer. Blinded, integrity-checked case suite that measures whether an agent reasons correctly over those packages — per evidence axis, with enforced budgets. |

## Work together

- Use GitHub Issues to record tasks, owners, and the next concrete step.
- Work on a branch and open a pull request when a change is ready to share.
- Ask the repository owner for collaborator access to push branches. Without write access, fork the repository and submit a pull request if it is public.
- Keep API keys in local environment variables or the deployment platform's secret store.
- Keep datasets, model weights, and generated results outside Git; document their source and retrieval steps.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution workflow.

## Team decisions

- [ ] Choose a problem, intended user, and demo outcome.
- [ ] Add teammates as GitHub collaborators.
- [ ] Choose the runtime and dependency setup.
- [ ] Set up shared Modal access and Claude API access as needed.
- [ ] Document the data source, evaluation method, and demo instructions.
- [ ] Agree on a license before distributing the project for reuse.
