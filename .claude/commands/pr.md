# Create PR and iterate until CI passes

You are creating a pull request for the current changes and shepherding it through CI and review.

**Important:** Other agents may be working in this same repo. You may see changes you didn't make — that's normal. Include everything in the branch; don't try to split out "your" changes.

## Step 1: Deterministic preflight (single command)

Run one script to do the repetitive setup/check work with clear output:

```bash
uv run python scripts/pr_preflight.py --base origin/main
```

This script deterministically does all of the following:
- Prints branch/HEAD, working tree status, diff stat, and commit list vs `main`
- Fetches latest `origin/main`
- Runs merge-conflict preflight including merge simulation against `origin/main`
- Suggests `RECOMMENDED_BASE=<branch>` for PR creation
- Runs local tests (CI-equivalent unit test command)

If preflight fails, fix issues and rerun before continuing.

## Step 2: Branch and commit

If you're on `main`, create a new branch:
```bash
git checkout -b pr/$(date +%Y%m%d-%H%M%S)-$(git log -1 --format=%s | tr ' ' '-' | tr '[:upper:]' '[:lower:]' | cut -c1-40)
```

If you're already on a feature branch, stay on it.

Stage and commit all changes with a clear message summarizing the work:
```bash
git add -A
git commit -m "descriptive commit message"
```

If there are already commits on the branch, you can squash them:
```bash
git reset --soft $(git merge-base HEAD main)
git commit -m "descriptive commit message"
```

## Step 3: Choose base branch

Use `RECOMMENDED_BASE` from preflight script output. If preflight defaulted to `main`, use `main`.

## Step 4: Push and create PR

```bash
git push --force-with-lease -u origin HEAD
```

Determine the issue number from the branch name (branches are named `issue-XXX`):
```bash
ISSUE_NUM=$(git branch --show-current | grep -oE '[0-9]+' | head -1)
ISSUE_TITLE=$(agenttree issue show "$ISSUE_NUM" --field title 2>/dev/null || echo "")
```

Create the PR using `gh` with the base you determined. **PR titles MUST use the `[Issue X]` prefix format:**
```bash
gh pr create --base <base-branch> --title "[Issue $ISSUE_NUM] $DESCRIPTION" --body "## Summary
- bullet points of what changed

## Test plan
- [ ] CI passes
- [ ] Tests pass"
```

For example: `[Issue 42] Add user authentication flow`

If a PR already exists for this branch, skip creation:
```bash
gh pr view HEAD 2>/dev/null && echo "PR already exists" || gh pr create ...
```

## Step 5: Wait for CI and iterate

Now enter a check-fix loop. Repeat until CI is green and no unaddressed review comments:

### 5a. Wait for CI to start
```bash
sleep 30
```

### 5b. Check CI/review status (single command)
```bash
uv run python scripts/pr_ci_status.py --watch
```

### 5c. If CI fails

Read failing run logs with:
```bash
gh run view <run-id> --log-failed
```

Fix the issue, commit, and push:
```bash
uv run python scripts/pr_preflight.py --base origin/main --skip-tests
git add -A
git commit -m "fix: address CI failure - <what you fixed>"
git push
```

Go back to 5a.

### 5d. Check for review feedback
```bash
gh pr view HEAD --comments
gh api repos/{owner}/{repo}/pulls/{number}/reviews --jq '.[] | "\(.state): \(.body)"'
```

If there are requested changes:
1. Read the feedback carefully
2. Make the fixes
3. Commit and push
4. Go back to 5a

### 5e. All green

When CI passes and there are no unaddressed review comments, report success:
- Print the PR URL
- Summarize the final state (CI status, number of iterations)

## Guidelines

- **Don't give up after one CI failure.** Read the logs, fix the issue, push again. Most CI failures are fixable.
- **Keep commits clean.** Each fix should have a descriptive message.
- **Don't force-push after review.** Once reviewers have commented, use regular pushes so they can see incremental changes.
- **If stuck after 5 iterations**, stop and ask for help rather than spinning forever.
- **Run tests locally first** if the project has a test command (`uv run pytest`, `npm test`, etc.) — it's faster than waiting for CI.
