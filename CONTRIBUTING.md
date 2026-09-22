# Contributing

## Pick a task

Create or claim a GitHub Issue with a short description of the intended result. Keep changes small enough for another teammate to review during the hackathon.

## Make a change

```bash
git switch main
git pull --ff-only
git switch -c your-name/short-task
# Edit files, then stage the specific files you changed.
git add path/to/changed-file
git commit -m "Describe the change"
git push -u origin your-name/short-task
```

Open a pull request against `main`. Include what changed, how you checked it, and the related issue. For contributions from a fork, push to your fork and open the pull request into this repository.

## Before sharing

- Check that credentials, local configuration, and private data are not in your commit.
- Record dependencies and commands needed to reproduce your work.
- Describe any checks you ran and any known limitations.
- Ask a teammate to review changes before merging when possible.

## Access

The repository owner can invite teammates through **Settings → Collaborators**. Public visibility allows people to read and fork the repository; pushing branches requires write access.
