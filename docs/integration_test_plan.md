# Integration Test Plan for AgentTree Workflow

## Overview

This document outlines the integration tests needed to verify the complete AgentTree workflow, from issue creation through acceptance. Currently, the codebase has comprehensive **unit tests** but no **integration tests** that exercise the full workflow.

## Current State

- **Unit tests**: 4,958 lines across 9 test files in `tests/unit/`
- **Integration tests**: None (`tests/integration/` doesn't exist)
- **Test fixtures**: Basic container/host environment simulation in `conftest.py`

## Testing Strategy: What to Mock vs Run Real

### Should Run Real (in temp directories/repos)
| Component | Why Real |
|-----------|----------|
| File operations | Core workflow creates/reads files, easy to test in tmp_path |
| Git operations | Can create real git repos in temp directories |
| Hook execution (file-based) | `file_exists`, `section_check`, `field_check`, etc. |
| Stage transitions | Core workflow logic |
| Issue CRUD | Creates YAML files, markdown files |
| Config loading | Load from temp `.agenttree.yaml` |

### Should Be Mocked
| Component | Why Mock |
|-----------|----------|
| GitHub API (`gh` CLI) | Requires authentication, network calls |
| Container runtime | Heavy, external dependency |
| tmux sessions | Requires terminal, external process |
| Background sync polling | Timing-dependent |
| `subprocess.run` for external commands | Except git commands |

### Hybrid (Real + Mock)
| Component | Approach |
|-----------|----------|
| Git operations | Real git repo in tmp_path, but mock `git push` |
| `agenttree next` CLI | Call the Python function directly, mock external deps |
| Hook execution | Real validators, mock actions like `merge_pr` |

---

## Test Infrastructure Needed

### New Fixtures (`tests/conftest.py` additions)

```python
@pytest.fixture
def workflow_repo(tmp_path):
    """Create a full agenttree project structure for workflow testing.

    Creates:
    - Real git repo with initial commit
    - .agenttree.yaml with standard config
    - _agenttree/ directory structure
    - skills/ templates
    """

@pytest.fixture
def mock_github():
    """Mock all GitHub API calls.

    Tracks:
    - PR creation calls
    - PR approval calls
    - PR merge calls
    - PR status queries
    """

@pytest.fixture
def mock_container():
    """Mock container/tmux operations.

    Simulates agent execution without actual containers.
    """

@pytest.fixture
def workflow_issue(workflow_repo):
    """Create a test issue ready for workflow testing."""
```

### Helper Functions

```python
def advance_issue_to_stage(issue_id: str, target_stage: str, worktree_path: Path):
    """Helper to advance an issue to a specific stage with valid content."""

def create_valid_problem_md(path: Path):
    """Create a problem.md that passes all DEFINE hooks."""

def create_valid_research_md(path: Path):
    """Create a research.md that passes all RESEARCH hooks."""

def create_valid_spec_md(path: Path):
    """Create a spec.md that passes all PLAN hooks."""

def create_valid_review_md(path: Path, average: float = 8.0):
    """Create a review.md that passes all IMPLEMENT hooks."""
```

---

## Integration Test Categories

### 1. Full Workflow Tests (Happy Path)

**File**: `tests/integration/test_full_workflow.py`

#### `test_issue_backlog_to_define`
- Create issue at backlog
- Start issue (mocked container)
- Verify: stage=define, substage=refine, worktree created, branch created

#### `test_define_to_research`
- Issue at define.refine with valid problem.md
- Run `agenttree next`
- Verify: stage=research, substage=explore, research.md created

#### `test_research_to_plan`
- Issue at research.document with valid research.md
- Run `agenttree next`
- Verify: stage=plan, substage=draft, spec.md created

#### `test_plan_through_to_plan_review`
- Issue at plan.draft
- Advance through: plan.refine → plan_assess → plan_revise → plan_review
- Verify: agent STOPS at plan_review (human_review gate)

#### `test_plan_review_approval`
- Issue at plan_review with valid spec.md
- Run `agenttree approve` (host environment)
- Verify: stage=implement, rebase hook ran

#### `test_implement_through_all_substages`
- Issue at implement.setup
- Advance through: setup → code → code_review → address_review → wrapup → feedback
- Verify: review.md created, all hooks pass, agent STOPS at implementation_review

#### `test_implementation_review_to_accepted`
- Issue at implementation_review with PR (mocked)
- Run `agenttree approve`
- Verify: stage=accepted, merge_pr hook ran, cleanup ran

#### `test_full_workflow_end_to_end`
- Create issue, advance through ALL stages
- Uses helper functions to create valid content at each stage
- Verifies entire lifecycle works

### 2. Hook Validation Tests

**File**: `tests/integration/test_workflow_hooks.py`

#### `test_define_blocks_without_context`
- Issue at define.refine with empty Context section
- `agenttree next` should fail with validation error

#### `test_research_blocks_without_relevant_files`
- Issue at research.document with empty Relevant Files
- `agenttree next` should fail

#### `test_plan_blocks_without_approach`
- Issue at plan.refine with empty Approach section
- `agenttree next` should fail

#### `test_implement_wrapup_blocks_low_score`
- Issue at implement.address_review with average < 7
- `agenttree next` should fail with "average must be at least 7"

#### `test_implement_feedback_blocks_without_commits`
- Issue at implement.wrapup with no commits
- `agenttree next` should fail with "No commits to push"

#### `test_implement_feedback_blocks_with_critical_issues`
- Issue at implement.wrapup with non-empty Critical Issues
- `agenttree next` should fail

#### `test_code_review_blocks_unchecked_items`
- Issue at implement.code with unchecked Self-Review Checklist
- `agenttree next` should fail

### 3. Human Review Gate Tests

**File**: `tests/integration/test_human_gates.py`

#### `test_agent_cannot_pass_plan_review`
- Issue at plan_revise (container environment)
- `agenttree next` advances to plan_review
- Further `agenttree next` should NOT advance (human gate)

#### `test_agent_cannot_pass_implementation_review`
- Issue at implement.feedback (container environment)
- `agenttree next` advances to implementation_review
- Further `agenttree next` should NOT advance (human gate)

#### `test_host_can_approve_plan_review`
- Issue at plan_review (host environment)
- `agenttree approve` should advance to implement

#### `test_host_can_approve_implementation_review`
- Issue at implementation_review (host environment, mocked gh)
- `agenttree approve` should advance to accepted

#### `test_approve_without_required_files_fails`
- Issue at plan_review without spec.md
- `agenttree approve` should fail

### 4. Edge Case Tests (from workflow_analysis.md)

**File**: `tests/integration/test_edge_cases.py`

#### Handled Edge Cases (verify they work)

##### `test_uncommitted_changes_before_pr`
- Issue at implement.feedback with uncommitted changes
- Sync detects issue at implementation_review
- `ensure_pr_for_issue()` should auto-commit before push
- Verify: commit created, PR created (mocked)

##### `test_uncommitted_changes_before_rebase`
- Issue at plan_review with uncommitted changes
- `agenttree approve` runs rebase hook
- Verify: auto-commit happens before rebase

##### `test_section_check_accepts_h2_and_h3`
- Issue with `## Approach` header
- Issue with `### Approach` header
- Both should pass section_check

##### `test_pr_merged_externally`
- Issue at implementation_review with PR
- Mock PR as merged on GitHub
- `check_merged_prs()` should detect and advance to accepted

##### `test_self_approval_shows_skip_flag`
- Issue at implementation_review where user is PR author
- `agenttree approve` should show message about `--skip-approval`

##### `test_orphaned_agent_cleanup_on_move`
- Issue with assigned agent
- Move to backlog via web endpoint
- Agent should be cleaned up

#### Edge Cases By Design (verify blocking behavior)

##### `test_low_review_score_blocks_agent`
- Set average to 6 in review.md
- `agenttree next` at address_review should fail
- Agent must fix before proceeding

##### `test_critical_issues_block_agent`
- Add content to Critical Issues section
- `agenttree next` at wrapup should fail

##### `test_missing_required_sections_block`
- Remove Approach from spec.md
- Transition should fail with clear error

### 5. Host/Container Boundary Tests

**File**: `tests/integration/test_host_container_boundary.py`

#### `test_container_skips_host_only_hooks`
- Issue at implementation_review (container environment)
- Hooks like `merge_pr`, `pr_approved` should skip
- No errors, just skipped

#### `test_host_runs_host_only_hooks`
- Issue at implementation_review (host environment)
- `agenttree approve` should run `pr_approved`, `merge_pr`

#### `test_pr_creation_happens_via_host_sync`
- Issue at implementation_review (created by agent in container)
- Agent can't create PR
- Host sync creates PR via `ensure_pr_for_issue()`

#### `test_rebase_only_runs_on_host`
- Issue at plan_review
- Rebase hook has `host_only: true`
- In container: skip silently
- On host: execute rebase

### 6. Multi-Issue Tests

**File**: `tests/integration/test_multi_issue.py`

#### `test_blocked_issue_waits_for_dependency`
- Issue A at implement
- Issue B blocked_by: [A]
- B should not start automatically

#### `test_blocked_issue_starts_when_unblocked`
- Issue A at accepted (just finished)
- Issue B was blocked_by: [A], now unblocked
- `start_blocked_issues` hook should start B

#### `test_multiple_issues_same_file`
- Issue A and B both modify same file
- Test conflict detection/handling (or document gap)

### 7. Error Recovery Tests

**File**: `tests/integration/test_error_recovery.py`

#### `test_hook_failure_preserves_state`
- Hook fails mid-transition
- Issue state should NOT be corrupted
- Can retry after fixing

#### `test_partial_hook_execution`
- Multiple hooks, second one fails
- Verify first hook's effects are rolled back (or documented)

#### `test_restart_from_failed_state`
- Issue stuck in bad state
- Can manually fix and continue

---

## Test Directory Structure

```
tests/
├── conftest.py                          # Global fixtures (existing)
├── unit/                                # Existing unit tests
│   ├── test_hooks.py
│   ├── test_issues.py
│   └── ...
└── integration/
    ├── __init__.py
    ├── conftest.py                      # Integration-specific fixtures
    ├── helpers.py                       # Workflow helper functions
    ├── test_full_workflow.py            # End-to-end workflow tests
    ├── test_workflow_hooks.py           # Hook validation in context
    ├── test_human_gates.py              # Human review gate tests
    ├── test_edge_cases.py               # Edge cases from workflow_analysis.md
    ├── test_host_container_boundary.py  # Host/container differences
    ├── test_multi_issue.py              # Multi-issue scenarios
    └── test_error_recovery.py           # Error handling tests
```

---

## Implementation Priority

### Phase 1: Foundation (Essential)
1. Create `tests/integration/conftest.py` with fixtures
2. Create `tests/integration/helpers.py` with content generators
3. Implement `test_full_workflow.py` - happy path end-to-end

### Phase 2: Validation (Important)
4. Implement `test_workflow_hooks.py` - hook blocking behavior
5. Implement `test_human_gates.py` - review gates work correctly

### Phase 3: Edge Cases (Thorough)
6. Implement `test_edge_cases.py` - document edge case handling
7. Implement `test_host_container_boundary.py` - container/host differences

### Phase 4: Advanced (Complete)
8. Implement `test_multi_issue.py` - issue dependencies
9. Implement `test_error_recovery.py` - error handling

---

## Mocking Strategy Details

### GitHub API Mock

```python
class MockGitHub:
    """Track and control GitHub API responses."""

    def __init__(self):
        self.created_prs = []
        self.approved_prs = []
        self.merged_prs = []
        self.pr_states = {}  # pr_number -> state dict

    def mock_pr_create(self, title, body):
        pr_num = len(self.created_prs) + 1
        self.created_prs.append({"number": pr_num, "title": title})
        self.pr_states[pr_num] = {"merged": False, "approved": False}
        return pr_num

    def mock_pr_merge(self, pr_number):
        self.merged_prs.append(pr_number)
        self.pr_states[pr_number]["merged"] = True

    def mock_pr_approve(self, pr_number):
        self.approved_prs.append(pr_number)
        self.pr_states[pr_number]["approved"] = True
```

### Container/Agent Mock

```python
class MockAgent:
    """Simulate agent execution without real container."""

    def __init__(self, issue_id, worktree_path):
        self.issue_id = issue_id
        self.worktree_path = worktree_path
        self.commands_run = []

    def run_next(self):
        """Simulate agent running `agenttree next`."""
        # Call the actual Python functions but with mocked externals
        from agenttree.cli import next_command
        # ... invoke with appropriate context
```

---

## Running Integration Tests

```bash
# Run all tests
uv run pytest

# Run only integration tests
uv run pytest tests/integration/

# Run specific integration test file
uv run pytest tests/integration/test_full_workflow.py

# Run with verbose output
uv run pytest tests/integration/ -v

# Run integration tests with coverage
uv run pytest tests/integration/ --cov=agenttree --cov-report=html
```

---

## Success Criteria

1. **Full workflow passes**: An issue can go from backlog → accepted with valid content
2. **Invalid content blocks**: Each required validation blocks with clear error
3. **Human gates work**: Agent cannot pass plan_review or implementation_review
4. **Edge cases handled**: All "✅ Handled" cases from workflow_analysis.md pass
5. **Container/host boundary**: Hooks behave correctly in both environments
6. **No regressions**: All existing unit tests continue to pass

---

## Notes

- Integration tests will be slower than unit tests due to git operations
- Consider marking slow tests with `@pytest.mark.slow`
- Some tests may need `@pytest.mark.skipif` for CI environments without git
- GitHub mock should be reusable across multiple test files
