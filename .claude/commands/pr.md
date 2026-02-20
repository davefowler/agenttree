# Create PR and iterate until CI passes

You are creating a pull request for the current changes and shepherding it through CI and review.

**Important:** Other agents may be working in this same repo. You may see changes you didn't make — that's normal. Include everything in the branch; don't try to split out "your" changes.

## Step 1: Assess the changes

```bash
git status
git diff --stat main...HEAD
git log --oneline main..HEAD
```

Understand what changed. Read modified files if needed to write a good commit message and PR description.

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

## Step 3: Find the right base branch

Before pushing, check if your branch shares commit history with any open PRs. If it does, base your PR on that branch instead of `main` to avoid duplicate commits and a bloated diff.

```bash
gh pr list --state open --json number,title,headRefName,baseRefName --limit 50
```

For each open PR's branch, check if it's an ancestor of your current HEAD:

```bash
git fetch origin <pr-branch>
git merge-base --is-ancestor origin/<pr-branch> HEAD && echo "ANCESTOR" || echo "no"
```

**Choose your base:**
- If an open PR's branch is an ancestor of HEAD → use that branch as your base (`--base <pr-branch>`)
- If multiple are ancestors → use the one closest to HEAD (most commits in common)
- If none are ancestors → use `main`

To find the closest ancestor among multiple candidates:
```bash
# The branch with the highest merge-base commit (closest to HEAD) wins
git merge-base HEAD origin/<branch>
```

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

### 5b. Check CI status
```bash
gh pr checks HEAD --watch --fail-fast
```

Or poll manually:
```bash
gh pr checks HEAD
```

### 5c. If CI fails

Read the failing check logs:
```bash
gh run list --branch $(git branch --show-current) --limit 5 --json status,conclusion,name
```

Find the failing run and read its logs:
```bash
gh run view <run-id> --log-failed
```

Fix the issue, commit, and push:
```bash
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
