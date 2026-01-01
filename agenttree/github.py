"""GitHub integration for AgentTree."""

import json
import shutil
import subprocess
import time
from typing import Dict, List, Optional
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
            ["pr", "checks", str(pr_number), "--json", "name,state,conclusion"]
        )
        data = json.loads(output)

        return [
            CheckStatus(
                name=check["name"],
                state=check["state"],
                conclusion=check.get("conclusion"),
            )
            for check in data
        ]
    except RuntimeError:
        return []


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
            # Check if all passed
            all_passed = all(
                check.state == "SUCCESS"
                or check.conclusion == "success"
                for check in checks
            )
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
