# Contributing to Novel Tandem Repeats

Thanks for taking part in the hackathon! This guide covers the quick workflow for
contributing changes via a pull request (PR).

## Quick start

1. **Fork the repo** (external contributors) or **clone it directly** (team members
   with write access):

   ```bash
   git clone https://github.com/collaborativebioinformatics/inTRuder.git
   cd inTRuder
   ```

2. **Create a branch** off `main` with a short, descriptive name:

   ```bash
   git checkout -b feature/short-description
   ```

3. **Make your changes.** Keep commits focused and write clear commit messages:

   ```bash
   git add <files>
   git commit -m "Add TR detection step to pipeline"
   ```

4. **Push your branch:**

   ```bash
   git push origin feature/short-description
   ```

5. **Open a pull request** on GitHub against the `main` branch. Fill in the PR
   template, describe what you changed and why, and link any related issue
   (e.g. `Closes #12`).

6. **Request a review** from a teammate. Address any feedback by pushing more
   commits to the same branch — the PR updates automatically.

## Guidelines

- **Small, focused PRs** are easier to review and merge quickly — ideal for a hackathon pace.
- **Sync with `main` often** to avoid conflicts:

  ```bash
  git checkout main
  git pull origin main
  git checkout feature/short-description
  git merge main
  ```

- **Don't commit large data files.** If there are data files too large, we need to coordinate external storage for them. Let us know on Slack!
- **Document as you go** — update the README or `docs/` when you add a tool,
  script, or pipeline step.
- **Ask questions** in the team Slack channel (`#2026_group2_group10_tandem_repeats`)
  if you're unsure about anything.

## Reporting issues

Found a bug or have an idea? [Open an issue](https://github.com/collaborativebioinformatics/inTRuder/issues/new/choose)
using one of the provided templates.

Good luck, have fun, and learn lots!
