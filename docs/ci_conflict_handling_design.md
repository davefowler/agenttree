# CI Failure & Merge Conflict Handling Design

## The Problem

When an agent reaches `implementation_review`:
1. Host creates PR automatically
2. CI runs on GitHub
3. If CI fails or there are merge conflicts, the agent is stuck waiting at implementation_review with no feedback

Currently: Agent waits forever. Human must notice, fix, and manually intervene.

## Proposed Solution: Pre-Implementation Review Host Stage

Add a new **host-controlled** stage between `implement.feedback` and `implementation_review` that:
1. Creates the PR
2. Waits for CI to complete
3. If CI fails or conflicts exist → notifies agent and steps back
4. If CI passes and no conflicts → advances to implementation_review

### Why Host-Controlled?

- **Rebase/merge requires host** - Agent in container can't do git remote operations
- **CI polling needs `gh` CLI** - Container doesn't have it
- **Clean separation** - Agent does code, host does PR management

## Implementation Options

### Option A: New `pr_ready` Stage (Recommended)

```yaml
stages:
  # ... implement substages ...

  - name: pr_ready
    host: controller  # Host runs this, not agent
    post_start:
      - create_pr:      # Creates PR if not exists
      - wait_for_ci:    # Polls CI status
          timeout: 600  # 10 minutes
          on_failure: step_back  # Go back to implement.feedback
      - check_conflicts:
          on_conflict: step_back
    # If all pass, auto-advance to implementation_review

  - name: implementation_review
    human_review: true
    # ... existing config ...
```

**Flow:**
```
implement.feedback → pr_ready (host) → implementation_review
                          ↓ (on failure)
                     implement.feedback (agent notified)
```

### Option B: Hooks in implementation_review.post_start

```yaml
- name: implementation_review
  human_review: true
  host: controller
  post_start:
    - create_pr:
    - wait_for_ci:
        timeout: 600
        on_failure:
          - send_message: "CI failed. Please check {{pr_url}} and fix the issues."
          - step_back_to: implement.code
    - check_conflicts:
        on_conflict:
          - rebase:  # Try auto-rebase first
          - on_failure:
            - send_message: "Merge conflicts detected. Please rebase and resolve."
            - step_back_to: implement.code
```

**Pros:** Simpler, no new stage
**Cons:** Mixes concerns (PR creation + human review gate)

### Option C: Background Polling Hook

```yaml
- name: implementation_review
  human_review: true
  host: controller
  post_start:
    - create_pr:
    - poll_pr_status:  # Runs in background
        interval: 60   # Check every minute
        on_ci_failure:
          - step_back_to: implement.code
          - send_message: "CI failed: {{ci_error}}"
        on_conflict:
          - step_back_to: implement.code
          - send_message: "Conflicts detected, please rebase"
```

**Pros:** Non-blocking, continuous monitoring
**Cons:** More complex, background process management

## Recommended Implementation: Option A

### New Hooks Needed

#### 1. `wait_for_ci` Hook

```python
def _action_wait_for_ci(
    pr_number: int,
    timeout: int = 600,
    poll_interval: int = 30,
    **kwargs
) -> tuple[bool, str]:
    """Wait for CI checks to complete on a PR.

    Returns:
        (success, error_message)
    """
    from agenttree.github import get_pr_checks_status

    start = time.time()
    while time.time() - start < timeout:
        status = get_pr_checks_status(pr_number)

        if status == "success":
            return True, ""
        elif status == "failure":
            return False, f"CI checks failed on PR #{pr_number}"
        elif status == "pending":
            time.sleep(poll_interval)
            continue

    return False, f"CI checks timed out after {timeout}s"
```

#### 2. `check_conflicts` Hook

```python
def _action_check_conflicts(
    pr_number: int,
    auto_rebase: bool = True,
    **kwargs
) -> tuple[bool, str]:
    """Check if PR has merge conflicts.

    Returns:
        (no_conflicts, error_message)
    """
    from agenttree.github import get_pr_mergeable_status

    mergeable = get_pr_mergeable_status(pr_number)

    if mergeable:
        return True, ""

    if auto_rebase:
        # Try to rebase
        success = rebase_issue_branch(kwargs.get("issue_id"))
        if success:
            # Force push after rebase
            push_branch_to_remote(kwargs.get("branch"), force=True)
            return True, ""

    return False, f"PR #{pr_number} has merge conflicts"
```

#### 3. `step_back` Hook

```python
def _action_step_back(
    issue_id: str,
    to_stage: str,
    to_substage: Optional[str] = None,
    message: str = "",
    **kwargs
) -> None:
    """Step an issue back to a previous stage and notify agent.

    Used when CI fails or conflicts detected.
    """
    from agenttree.issues import update_issue_stage
    from agenttree.tmux import send_keys
    from agenttree.state import get_active_agent

    # Update stage
    update_issue_stage(issue_id, to_stage, to_substage)

    # Notify agent
    agent = get_active_agent(issue_id)
    if agent and message:
        full_message = f"{message}\n\nRun 'agenttree next' to see updated instructions."
        send_keys(agent.tmux_session, full_message)
```

### Config Changes

```yaml
stages:
  # ... existing stages ...

  - name: implement
    substages:
      # ... existing substages ...
      feedback:
        pre_completion:
          - has_commits:
          - file_exists: review.md
          - section_check:
              file: review.md
              section: Critical Issues
              expect: empty

  - name: pr_ready
    host: controller
    post_start:
      - create_pr:
      - wait_for_ci:
          timeout: 600
          poll_interval: 30
      - check_conflicts:
          auto_rebase: true
    pre_completion:
      - pr_ci_passed:  # Validator to confirm CI is green
      - pr_mergeable:  # Validator to confirm no conflicts
    on_failure:
      step_back_to: implement.feedback
      message: "{{failure_reason}}"

  - name: implementation_review
    human_review: true
    pre_completion:
      - pr_approved:

  # ... rest of stages ...
```

### Skill Instructions for Agent

When stepped back due to CI failure:

```markdown
## CI Failure

Your PR failed CI checks. Please:

1. Check the CI logs: {{pr_url}}/checks
2. Fix the failing tests/lint issues
3. Commit your fixes
4. Run `agenttree next` to retry

Common issues:
- Failing tests: Run `agenttree test` locally first
- Lint errors: Run `agenttree lint` to check
- Type errors: Run `uv run mypy agenttree`
```

When stepped back due to conflicts:

```markdown
## Merge Conflicts

Your PR has merge conflicts with main. Please:

1. Rebase your branch: `git fetch origin && git rebase origin/main`
2. Resolve any conflicts
3. Run tests to make sure nothing broke
4. Commit your changes
5. Run `agenttree next` to retry

Auto-rebase was attempted but failed. Manual resolution needed.
```

## Alternative: Simpler Hook-Only Approach

If we don't want a new stage, we can add hooks to `implementation_review.post_start`:

```yaml
- name: implementation_review
  human_review: true
  host: controller
  post_start:
    - create_pr:
    - run: |
        # Wait for CI (simple script approach)
        pr_number={{pr_number}}
        for i in {1..20}; do
          status=$(gh pr checks $pr_number --json state -q '.[] | select(.state != "SUCCESS" and .state != "PENDING") | .state' 2>/dev/null)
          if [ -z "$status" ]; then
            # All passed or still pending
            all_done=$(gh pr checks $pr_number --json state -q 'all(.[]; .state == "SUCCESS")')
            if [ "$all_done" = "true" ]; then
              exit 0  # Success
            fi
          else
            echo "CI failed"
            exit 1
          fi
          sleep 30
        done
        echo "CI timeout"
        exit 1
      on_failure:
        step_back_to: implement.feedback
        message: "CI checks failed. Please fix and retry."
```

## Recommendation

**Start with Option A (new `pr_ready` stage)** because:

1. **Clean separation** - PR management is its own concern
2. **Retry-friendly** - Agent can fix and re-advance through feedback → pr_ready
3. **Extensible** - Easy to add more checks (security scans, coverage, etc.)
4. **Debuggable** - Clear stage shows where issues are stuck

## Implementation Steps

1. Add `wait_for_ci` hook to `hooks.py`
2. Add `check_conflicts` hook to `hooks.py`
3. Add `step_back` action to `hooks.py`
4. Add `pr_ready` stage to `.agenttree.yaml`
5. Add skill instructions for CI failure / conflict scenarios
6. Add tests for the new hooks

## Configuration Options

All options should be configurable in `.agenttree.yaml`:

```yaml
ci_polling:
  timeout_s: 600           # 10 min default, configurable
  poll_interval_s: 30      # How often to check
  max_retries: 5           # Max CI failure loops before requiring human intervention
  on_failure: step_back    # What to do on CI failure

conflict_handling:
  auto_rebase: true        # Try auto-rebase before asking agent
  notify_on_rebase: true   # Always tell agent when rebase was done
  max_conflict_retries: 3  # Max times to step back for conflicts
```

## Resolved Questions

1. **Timeout duration?** - 10 min default, configurable via `ci_polling.timeout_s`
2. **Max retries?** - Yes, configurable via `ci_polling.max_retries` and `conflict_handling.max_conflict_retries`
3. **Auto-rebase?** - Yes, try auto-rebase first, but always notify agent via `conflict_handling.notify_on_rebase`
4. **Notification method?** - tmux send-keys for now; can add slack/email later
