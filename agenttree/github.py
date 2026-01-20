"""GitHub integration for AgentTree."""

import json
import shutil
import subprocess
import time
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class Issue:
    """GitHub issue information."""

    number: int
    title: str
    body: str
    url: str
    labels: List[str]


@dataclass
class PullRequest:
    """GitHub pull request information."""

    number: int
    title: str
    url: str
    branch: str


@dataclass
class CheckStatus:
    """CI check status."""

    name: str
    state: str  # SUCCESS, FAILURE, PENDING
    conclusion: Optional[str] = None
    link: Optional[str] = None  # URL to the check run details


@dataclass
class IssueWithContext:
    """Issue with additional context for display."""

    number: int
    title: str
    body: str
    url: str
    labels: List[str]
    state: str
    assignees: List[str]
    created_at: str
    updated_at: str
    stage: Optional[int] = None
    is_review: bool = False


def ensure_gh_cli() -> None:
    """Ensure gh CLI is installed and authenticated.

    Raises:
        RuntimeError: If gh not found or not authenticated
    """
    if not shutil.which("gh"):
        raise RuntimeError(
            "GitHub CLI (gh) not found.\n\n"
            "Install: https://cli.github.com/\n"
            "  macOS:   brew install gh\n"
            "  Linux:   See https://github.com/cli/cli#installation\n"
            "  Windows: See https://github.com/cli/cli#installation\n"
        )

    # Check if authenticated
    result = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Not authenticated with GitHub.\n\n"
            "Run: gh auth login\n\n"
            "This will open your browser to authenticate.\n"
        )


def gh_command(args: List[str]) -> str:
    """Run a gh (GitHub CLI) command.

    Args:
        args: Command arguments

    Returns:
        Command output

    Raises:
        RuntimeError: If gh command fails
    """
    try:
        result = subprocess.run(
            ["gh"] + args,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"GitHub CLI command failed: {e.stderr}") from e


def get_issue(issue_number: int) -> Issue:
    """Get information about a GitHub issue.

    Args:
        issue_number: Issue number

    Returns:
        Issue object
    """
    output = gh_command(
        ["issue", "view", str(issue_number), "--json", "number,title,body,url,labels"]
    )
    data = json.loads(output)

    labels = [label["name"] for label in data.get("labels", [])]

    return Issue(
        number=data["number"],
        title=data["title"],
        body=data.get("body", ""),
        url=data["url"],
        labels=labels,
    )


def add_label_to_issue(issue_number: int, label: str) -> None:
    """Add a label to an issue.

    Args:
        issue_number: Issue number
        label: Label to add
    """
    try:
        gh_command(["issue", "edit", str(issue_number), "--add-label", label])
    except RuntimeError:
        # Label might not exist or issue might not exist
        pass


def remove_label_from_issue(issue_number: int, label: str) -> None:
    """Remove a label from an issue.

    Args:
        issue_number: Issue number
        label: Label to remove
    """
    try:
        gh_command(["issue", "edit", str(issue_number), "--remove-label", label])
    except RuntimeError:
        pass


def create_pr(title: str, body: str, branch: str, base: str = "main") -> PullRequest:
    """Create a pull request.

    Args:
        title: PR title
        body: PR body
        branch: Source branch
        base: Base branch (default: main)

    Returns:
        Created PullRequest object
    """
    output = gh_command(
        [
            "pr",
            "create",
            "--title",
            title,
            "--body",
            body,
            "--base",
            base,
            "--head",
            branch,
        ]
    )

    # Extract PR number from URL
    pr_url = output.strip()
    pr_number = int(pr_url.split("/")[-1])

    return PullRequest(number=pr_number, title=title, url=pr_url, branch=branch)


def get_pr_checks(pr_number: int) -> List[CheckStatus]:
    """Get CI check status for a PR.

    Args:
        pr_number: PR number

    Returns:
        List of check statuses
    """
    try:
        output = gh_command(
            ["pr", "checks", str(pr_number), "--json", "name,state,link"]
        )
        data = json.loads(output)

        return [
            CheckStatus(
                name=check["name"],
                state=check["state"],
                link=check.get("link"),
            )
            for check in data
        ]
    except RuntimeError:
        return []


@dataclass
class PRComment:
    """PR comment information."""

    author: str
    body: str
    created_at: str


def get_pr_comments(pr_number: int) -> List[PRComment]:
    """Get comments on a PR.

    Args:
        pr_number: PR number

    Returns:
        List of comments
    """
    try:
        output = gh_command(
            ["pr", "view", str(pr_number), "--json", "comments", "--jq", ".comments"]
        )
        if not output or output == "null":
            return []

        data = json.loads(output)
        return [
            PRComment(
                author=comment.get("author", {}).get("login", "unknown"),
                body=comment.get("body", ""),
                created_at=comment.get("createdAt", ""),
            )
            for comment in data
        ]
    except RuntimeError:
        return []


def get_check_failed_logs(check: CheckStatus, max_lines: int = 200) -> Optional[str]:
    """Get the failed logs for a CI check.

    Extracts run_id and job_id from the check link and fetches logs.

    Args:
        check: CheckStatus with link field populated
        max_lines: Maximum number of log lines to return

    Returns:
        Failed log output as string, or None if unable to fetch
    """
    import re

    if not check.link:
        return None

    # Extract run_id and job_id from link like:
    # https://github.com/owner/repo/actions/runs/12345/job/67890
    match = re.search(r'/actions/runs/(\d+)/job/(\d+)', check.link)
    if not match:
        return None

    run_id, job_id = match.groups()

    try:
        result = subprocess.run(
            ["gh", "run", "view", run_id, "--job", job_id, "--log-failed"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split('\n')
            if len(lines) > max_lines:
                lines = lines[-max_lines:]  # Keep last N lines
                return f"... (truncated, showing last {max_lines} lines) ...\n" + '\n'.join(lines)
            return result.stdout.strip()
        return None
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return None


def wait_for_ci(
    pr_number: int, timeout: int = 600, poll_interval: int = 30
) -> bool:
    """Wait for CI checks to complete.

    Args:
        pr_number: PR number
        timeout: Maximum time to wait in seconds
        poll_interval: How often to poll in seconds

    Returns:
        True if all checks passed, False if any failed or timeout
    """
    elapsed = 0

    while elapsed < timeout:
        checks = get_pr_checks(pr_number)

        if not checks:
            # No checks yet, keep waiting
            time.sleep(poll_interval)
            elapsed += poll_interval
            continue

        # Check if all are complete
        all_complete = all(check.state != "PENDING" for check in checks)

        if all_complete:
            # Check if all passed (state is SUCCESS when check passes)
            all_passed = all(check.state == "SUCCESS" for check in checks)
            return all_passed

        # Still pending, keep waiting
        time.sleep(poll_interval)
        elapsed += poll_interval

    # Timeout
    return False


def close_issue(issue_number: int) -> None:
    """Close a GitHub issue.

    Args:
        issue_number: Issue number
    """
    gh_command(["issue", "close", str(issue_number)])


def is_pr_approved(pr_number: int) -> bool:
    """Check if a PR has been approved.

    Args:
        pr_number: PR number

    Returns:
        True if PR is approved
    """
    output = gh_command([
        "api",
        f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/reviews",
        "--jq",
        '[.[] | select(.state == "APPROVED")] | length'
    ])

    approvals = int(output.strip())
    return approvals > 0


def merge_pr(pr_number: int, method: str = "squash") -> None:
    """Merge a pull request.

    Args:
        pr_number: PR number
        method: Merge method (squash, merge, rebase)
    """
    gh_command([
        "pr",
        "merge",
        str(pr_number),
        f"--{method}",
        "--delete-branch"
    ])


def auto_merge_if_ready(pr_number: int, require_approval: bool = True) -> bool:
    """Auto-merge PR if CI passes and (optionally) approved.

    Args:
        pr_number: PR number
        require_approval: Whether to require approval before merging

    Returns:
        True if PR was merged, False otherwise
    """
    # Check if CI is passing
    ci_passed = wait_for_ci(pr_number, timeout=0)  # Just check current state

    if not ci_passed:
        return False

    # Check approval if required
    if require_approval and not is_pr_approved(pr_number):
        return False

    # All checks passed, merge it
    try:
        merge_pr(pr_number)
        return True
    except RuntimeError:
        return False


def link_pr_to_issue(pr_number: int, issue_number: int) -> None:
    """Link a PR to an issue (adds closing keyword).

    Args:
        pr_number: PR number
        issue_number: Issue number
    """
    # Get current PR body
    output = gh_command([
        "pr",
        "view",
        str(pr_number),
        "--json",
        "body",
        "--jq",
        ".body"
    ])

    current_body = output.strip()

    # Add closing keyword if not already present
    closing_text = f"\n\nCloses #{issue_number}"
    if f"#{issue_number}" not in current_body:
        new_body = current_body + closing_text
        gh_command([
            "pr",
            "edit",
            str(pr_number),
            "--body",
            new_body
        ])


def monitor_pr_and_auto_merge(
    pr_number: int,
    issue_number: Optional[int] = None,
    check_interval: int = 60,
    max_wait: int = 3600,
    require_approval: bool = True
) -> bool:
    """Monitor a PR and auto-merge when ready.

    This function will:
    1. Wait for CI to pass
    2. Check for approval (if required)
    3. Auto-merge when ready
    4. Close linked issue (if provided)

    Args:
        pr_number: PR number
        issue_number: Optional issue number to close on merge
        check_interval: Seconds between checks
        max_wait: Maximum seconds to wait
        require_approval: Whether to require approval

    Returns:
        True if PR was merged, False if timeout or failure
    """
    import time

    start_time = time.time()

    while time.time() - start_time < max_wait:
        # Try to auto-merge
        if auto_merge_if_ready(pr_number, require_approval):
            # PR merged successfully!
            if issue_number:
                # Close the linked issue
                close_issue(issue_number)
            return True

        # Not ready yet, wait and try again
        time.sleep(check_interval)

    return False


class GitHubManager:
    """Manages GitHub integration for AgentTree."""

    def __init__(self, agent_label_prefix: str = "agent-"):
        """Initialize GitHub manager.

        Args:
            agent_label_prefix: Prefix for agent labels (default: "agent-")
        """
        self.agent_label_prefix = agent_label_prefix

    def get_agent_label(self, agent_num: int) -> str:
        """Get label for an agent.

        Args:
            agent_num: Agent number

        Returns:
            Label string
        """
        return f"{self.agent_label_prefix}{agent_num}"

    def assign_issue_to_agent(self, issue_number: int, agent_num: int) -> None:
        """Assign an issue to an agent by adding a label.

        Args:
            issue_number: Issue number
            agent_num: Agent number
        """
        label = self.get_agent_label(agent_num)
        add_label_to_issue(issue_number, label)

    def unassign_issue_from_agent(self, issue_number: int, agent_num: int) -> None:
        """Unassign an issue from an agent.

        Args:
            issue_number: Issue number
            agent_num: Agent number
        """
        label = self.get_agent_label(agent_num)
        remove_label_from_issue(issue_number, label)

    def create_task_file(self, issue: Issue, output_path) -> None:
        """Create a TASK.md file from an issue.

        Args:
            issue: Issue object
            output_path: Path to write TASK.md
        """
        content = f"""# Task: {issue.title}

**Issue:** [#{issue.number}]({issue.url})

## Description

{issue.body}

## Workflow

```bash
git checkout -b issue-{issue.number}
# ... implement changes ...
git commit -m "Your message (Fixes #{issue.number})"
./scripts/submit.sh
```
"""
        with open(output_path, "w") as f:
            f.write(content)

    def create_adhoc_task_file(self, task_description: str, output_path) -> None:
        """Create a TASK.md file for an ad-hoc task.

        Args:
            task_description: Task description
            output_path: Path to write TASK.md
        """
        content = f"""# Task

{task_description}

## Workflow

```bash
git checkout -b feature/descriptive-name
# ... implement changes ...
git commit -m "Your message"
./scripts/submit.sh --no-issue
```
"""
        with open(output_path, "w") as f:
            f.write(content)


def list_issues(state: str = "open", labels: Optional[List[str]] = None) -> List[IssueWithContext]:
    """List GitHub issues with context.

    Args:
        state: Issue state (open, closed, all)
        labels: Optional list of labels to filter by

    Returns:
        List of issues with context
    """
    args = ["issue", "list", "--json", "number,title,body,url,labels,state,assignees,createdAt,updatedAt", "--limit", "100"]

    if state != "all":
        args.extend(["--state", state])

    if labels:
        for label in labels:
            args.extend(["--label", label])

    output = gh_command(args)

    if not output:
        return []

    data = json.loads(output)
    issues = []

    for item in data:
        labels_list = [label["name"] for label in item.get("labels", [])]
        assignees_list = [assignee["login"] for assignee in item.get("assignees", [])]

        # Extract stage from labels (look for "stage-N" pattern)
        stage = None
        is_review = False

        for label in labels_list:
            if label.startswith("stage-"):
                try:
                    stage = int(label.split("-")[1])
                except (IndexError, ValueError):
                    pass
            elif label.lower() in ["review", "needs-review", "in-review"]:
                is_review = True

        issues.append(IssueWithContext(
            number=item["number"],
            title=item["title"],
            body=item.get("body", ""),
            url=item["url"],
            labels=labels_list,
            state=item["state"],
            assignees=assignees_list,
            created_at=item["createdAt"],
            updated_at=item["updatedAt"],
            stage=stage,
            is_review=is_review
        ))

    return issues


def sort_issues_by_priority(issues: List[IssueWithContext]) -> List[IssueWithContext]:
    """Sort issues by priority: review stage first, then by stage (descending).

    Args:
        issues: List of issues to sort

    Returns:
        Sorted list of issues
    """
    def sort_key(issue: IssueWithContext):
        # First priority: review stage (True = 0, False = 1, so review comes first)
        # Second priority: stage (higher stages first, None last)
        # Third priority: issue number (lower numbers first for same stage)
        return (
            0 if issue.is_review else 1,  # Review issues first
            -(issue.stage or 0),  # Higher stages first (negative for descending)
            issue.number  # Lower issue numbers first
        )

    return sorted(issues, key=sort_key)
