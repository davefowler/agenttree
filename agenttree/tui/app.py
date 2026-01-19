"""Main TUI application for AgentTree issue management."""

from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Input, Static
from textual.worker import Worker, get_current_worker

from agenttree.hooks import (
    ValidationError,
    execute_exit_hooks,
    execute_enter_hooks,
)
from agenttree.issues import (
    Issue,
    get_issue,
    get_issue_dir,
    get_next_stage,
    list_issues,
    update_issue_stage,
)


# Rejection stage mappings: where to send issues back when rejected
# Only valid human review stages (plan_review, implementation_review) are included
REJECTION_MAPPINGS = {
    "plan_review": "plan",
    "implementation_review": "implement",
}


class DetailPanel(Static):
    """Panel showing detailed information about the selected issue."""

    DEFAULT_CSS = """
    DetailPanel {
        padding: 1 2;
        background: $surface;
        border: solid $primary;
    }
    """

    def __init__(self) -> None:
        super().__init__("Select an issue to view details", id="detail-panel")
        self._issue: Optional[Issue] = None

    def show_issue(self, issue: Issue) -> None:
        """Display details for the given issue."""
        self._issue = issue

        # Build detail content
        content = f"[bold]{issue.title}[/bold]\n\n"
        content += f"[dim]ID:[/dim] {issue.id}\n"
        content += f"[dim]Stage:[/dim] {issue.stage}"
        if issue.substage:
            content += f".{issue.substage}"
        content += "\n"
        content += f"[dim]Priority:[/dim] {issue.priority.value}\n"

        if issue.assigned_agent:
            content += f"[dim]Agent:[/dim] {issue.assigned_agent}\n"

        if issue.labels:
            content += f"[dim]Labels:[/dim] {', '.join(issue.labels)}\n"

        if issue.branch:
            content += f"[dim]Branch:[/dim] {issue.branch}\n"

        if issue.pr_url:
            content += f"[dim]PR:[/dim] {issue.pr_url}\n"

        # Try to load problem.md content
        issue_dir = get_issue_dir(issue.id)
        if issue_dir:
            problem_path = issue_dir / "problem.md"
            if problem_path.exists():
                try:
                    problem_content = problem_path.read_text()
                    # Show first ~500 chars of problem.md
                    if len(problem_content) > 500:
                        problem_content = problem_content[:500] + "..."
                    content += f"\n[dim]──── Problem ────[/dim]\n{problem_content}"
                except Exception:
                    pass

        self.update(content)

    def clear_issue(self) -> None:
        """Clear the detail panel."""
        self._issue = None
        self.update("Select an issue to view details")

    @property
    def issue(self) -> Optional[Issue]:
        """Return the currently displayed issue."""
        return self._issue


class FilterInput(Input):
    """Input field for filtering issues."""

    DEFAULT_CSS = """
    FilterInput {
        dock: top;
        margin: 0 0 1 0;
    }
    """

    def __init__(self) -> None:
        super().__init__(placeholder="Filter by stage or priority...", id="filter-input")


class StatusBar(Static):
    """Status bar for showing notifications."""

    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
        background: $primary;
        color: $text;
        text-align: center;
    }
    """

    def __init__(self) -> None:
        super().__init__("Ready", id="status-bar")

    def show_message(self, message: str) -> None:
        """Show a message in the status bar."""
        self.update(message)


# type: ignore[type-arg] - Textual library has incomplete type stubs for generic DataTable
class IssueTable(DataTable):  # type: ignore[type-arg]
    """DataTable widget for displaying issues."""

    DEFAULT_CSS = """
    IssueTable {
        height: 100%;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="issue-table", cursor_type="row")
        self._issues: list[Issue] = []
        self._filtered_issues: list[Issue] = []

    def on_mount(self) -> None:
        """Set up columns when mounted."""
        self.add_column("ID", key="id", width=6)
        self.add_column("Title", key="title")
        self.add_column("Stage", key="stage", width=22)
        self.add_column("Priority", key="priority", width=10)
        self.add_column("Agent", key="agent", width=7)

    def populate(self, issues: list[Issue]) -> None:
        """Populate the table with issues."""
        self._issues = issues
        self._filtered_issues = issues.copy()
        self._rebuild_rows()

    def _rebuild_rows(self) -> None:
        """Rebuild table rows from filtered issues."""
        self.clear()
        for issue in self._filtered_issues:
            stage_str = issue.stage
            if issue.substage:
                stage_str += f".{issue.substage}"

            agent_str = str(issue.assigned_agent) if issue.assigned_agent else "-"

            self.add_row(
                issue.id,
                issue.title[:40] + "..." if len(issue.title) > 40 else issue.title,
                stage_str,
                issue.priority.value,
                agent_str,
                key=issue.id,
            )

    def apply_filter(self, filter_text: str) -> None:
        """Filter issues by stage or priority."""
        if not filter_text:
            self._filtered_issues = self._issues.copy()
        else:
            filter_lower = filter_text.lower()
            self._filtered_issues = [
                issue for issue in self._issues
                if filter_lower in issue.stage.lower()
                or filter_lower in issue.priority.value.lower()
                or filter_lower in issue.title.lower()
            ]
        self._rebuild_rows()

    def get_selected_issue(self) -> Optional[Issue]:
        """Get the currently selected issue."""
        if not self._filtered_issues:
            return None
        if self.cursor_row < 0 or self.cursor_row >= len(self._filtered_issues):
            return None
        return self._filtered_issues[self.cursor_row]

    @property
    def issues(self) -> list[Issue]:
        """Return all loaded issues."""
        return self._issues


# type: ignore[type-arg] - Textual library has incomplete type stubs for generic App
class TUIApp(App):  # type: ignore[type-arg]
    """Terminal User Interface for AgentTree issue management."""

    CSS_PATH = "app.tcss"
    TITLE = "AgentTree Issues"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("a", "advance_stage", "Advance"),
        Binding("r", "reject", "Reject"),
        Binding("s", "start_agent", "Start"),
        Binding("slash", "focus_filter", "Filter", key_display="/"),
        Binding("R", "refresh", "Refresh"),
        Binding("escape", "clear_filter", "Clear", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._loading = False

    def compose(self) -> ComposeResult:
        """Create the UI layout."""
        yield Header()
        yield FilterInput()
        with Horizontal(id="main-container"):
            with Vertical(id="table-container"):
                yield IssueTable()
            yield DetailPanel()
        yield StatusBar()
        yield Footer()

    def on_mount(self) -> None:
        """Load issues when app starts."""
        self._load_issues()

    def _load_issues(self) -> None:
        """Load issues in a worker to avoid blocking UI."""
        self._loading = True
        self.query_one(StatusBar).show_message("Loading issues...")
        self.run_worker(self._fetch_issues, name="load_issues", exclusive=True, thread=True)

    def _fetch_issues(self) -> list[Issue]:
        """Fetch issues (runs in worker thread)."""
        worker = get_current_worker()
        if worker.is_cancelled:
            return []
        # Use sync=False to avoid blocking on git sync
        return list_issues(sync=False)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker completion."""
        if event.worker.name == "load_issues" and event.worker.is_finished:
            self._loading = False
            # Check for worker errors before accessing result
            if event.worker.error:
                self.query_one(StatusBar).show_message(f"Error loading issues: {event.worker.error}")
                return
            if event.worker.result:
                issues = event.worker.result
                table = self.query_one(IssueTable)
                table.populate(issues)
                status = self.query_one(StatusBar)
                status.show_message(f"Loaded {len(issues)} issues")
            else:
                self.query_one(StatusBar).show_message("No issues found")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection in the issue table."""
        table = self.query_one(IssueTable)
        issue = table.get_selected_issue()
        if issue:
            self.query_one(DetailPanel).show_issue(issue)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Handle row highlighting (cursor movement) in the issue table."""
        table = self.query_one(IssueTable)
        issue = table.get_selected_issue()
        if issue:
            self.query_one(DetailPanel).show_issue(issue)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle filter input changes."""
        if event.input.id == "filter-input":
            table = self.query_one(IssueTable)
            table.apply_filter(event.value)

    def action_focus_filter(self) -> None:
        """Focus the filter input."""
        self.query_one(FilterInput).focus()

    def action_clear_filter(self) -> None:
        """Clear the filter and refocus the table."""
        filter_input = self.query_one(FilterInput)
        filter_input.value = ""
        self.query_one(IssueTable).focus()

    def action_refresh(self) -> None:
        """Refresh the issue list."""
        self._load_issues()

    def action_advance_stage(self) -> None:
        """Advance the selected issue to the next stage."""
        table = self.query_one(IssueTable)
        selected_issue = table.get_selected_issue()
        status = self.query_one(StatusBar)

        if not selected_issue:
            status.show_message("No issue selected")
            return

        # Get fresh issue object for hooks
        issue = get_issue(selected_issue.id)
        if not issue:
            status.show_message(f"Issue #{selected_issue.id} not found")
            return

        try:
            next_stage, next_substage, _ = get_next_stage(issue.stage, issue.substage)

            # Execute pre-completion hooks (can block with ValidationError)
            from_stage = issue.stage
            from_substage = issue.substage
            execute_exit_hooks(issue, from_stage, from_substage)

            # Update issue stage
            updated = update_issue_stage(issue.id, next_stage, next_substage)
            if not updated:
                status.show_message(f"Failed to update issue #{issue.id}")
                return

            # Execute post-start hooks
            execute_enter_hooks(updated, next_stage, next_substage)

            status.show_message(f"Advanced #{issue.id} to {next_stage}")
            self._load_issues()
        except ValidationError as e:
            status.show_message(f"Cannot advance: {e}")
        except Exception as e:
            status.show_message(f"Failed to advance: {e}")

    def action_reject(self) -> None:
        """Reject the selected issue (send back to previous stage)."""
        table = self.query_one(IssueTable)
        selected_issue = table.get_selected_issue()
        status = self.query_one(StatusBar)

        if not selected_issue:
            status.show_message("No issue selected")
            return

        # Get fresh issue object for hooks
        issue = get_issue(selected_issue.id)
        if not issue:
            status.show_message(f"Issue #{selected_issue.id} not found")
            return

        # Check if issue is in a human review stage
        if issue.stage not in REJECTION_MAPPINGS:
            status.show_message(f"Cannot reject: {issue.stage} is not a review stage")
            return

        try:
            reject_to = REJECTION_MAPPINGS[issue.stage]

            # Execute exit hooks for the current stage (consistent with web UI)
            from_stage = issue.stage
            from_substage = issue.substage
            execute_exit_hooks(issue, from_stage, from_substage)

            # Update issue stage
            updated = update_issue_stage(issue.id, reject_to)
            if not updated:
                status.show_message(f"Failed to update issue #{issue.id}")
                return

            # Execute post-start hooks for the target stage
            execute_enter_hooks(updated, reject_to, None)

            status.show_message(f"Rejected #{issue.id} back to {reject_to}")
            self._load_issues()
        except ValidationError as e:
            status.show_message(f"Cannot reject: {e}")
        except Exception as e:
            status.show_message(f"Failed to reject: {e}")

    def action_start_agent(self) -> None:
        """Start an agent on the selected issue."""
        table = self.query_one(IssueTable)
        issue = table.get_selected_issue()
        status = self.query_one(StatusBar)

        if not issue:
            status.show_message("No issue selected")
            return

        if issue.assigned_agent:
            status.show_message(f"Issue #{issue.id} already has agent {issue.assigned_agent}")
            return

        # Note: Starting an agent requires more complex logic (worktree, tmux, etc.)
        # For now, just show a message - full implementation would call cli start logic
        status.show_message(f"Use 'agenttree start {issue.id}' to dispatch an agent")
