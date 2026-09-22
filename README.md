# Boston Computational Biology Hackathon — Team Workspace

Shared code and notes for our team's project at the [Boston Computational Biology Hackathon](https://luma.com/boston-comp-bio-hack), hosted by Anthropic, Modal, and Flagship Pioneering.

## Get started

```bash
git clone https://github.com/minojWittgen/boston-comp-bio-hack.git
cd boston-comp-bio-hack
git switch -c your-name/short-task
```

The current prototype collects target-reference knowledge and checks declared observations across species, experimental contexts, and modalities. Setup, API, and run instructions are linked below.

## Work together

- Use GitHub Issues to record tasks, owners, and the next concrete step.
- Work on a branch and open a pull request when a change is ready to share.
- Ask the repository owner for collaborator access to push branches. Without write access, fork the repository and submit a pull request if it is public.
- Keep API keys in local environment variables or the deployment platform's secret store.
- Keep datasets, model weights, and generated results outside Git; document their source and retrieval steps.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution workflow.

## Investigation coordinator

The coordinator builds on the data-pipeline branch and connects research intent,
fixed success criteria, evidence comparison and bounded follow-up. See the
[coordinator integration guide](coordinator/README.md),
[build plan and work boundaries](docs/plans/2026-09-22-coordinator-build.md), and
[offline synthetic examples](coordinator/examples/README.md).

## Team decisions

- [ ] Choose a problem, intended user, and demo outcome.
- [ ] Add teammates as GitHub collaborators.
- [ ] Choose the runtime and dependency setup.
- [ ] Set up shared Modal access and Claude API access as needed.
- [ ] Document the data source, evaluation method, and demo instructions.
- [ ] Agree on a license before distributing the project for reuse.
