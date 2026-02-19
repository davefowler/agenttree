# Testing Strategy

**Last Updated:** 2026-01-01
**Current Coverage:** 25% overall

## Philosophy

AgentTree's testing approach balances:
- **High coverage on core logic** - Business rules, algorithms, data transformations
- **Pragmatic mocking for I/O** - External systems, file operations, subprocess calls
- **Manual/integration for CLI** - User-facing commands, actual workflows
- **Skip platform-specific code** - Container runtimes, OS-specific features (not worth heavy mocking)

**Goal: 60-70% overall coverage** with focus on quality over quantity.

## Current Coverage

```
Module                  Coverage    Target     Notes
──────────────────────────────────────────────────────────────
config.py                  96%      98%       Just 2 edge cases
worktree.py                88%      90%       Missing error paths
agents_repo.py             57%      80%       Need template tests
github.py                   0%      60%       Mock GitHub API
tmux.py                     0%      50%       Integration tests
cli.py                      0%      40%       Click integration
container.py                0%      30%       Platform-specific
agents/base.py              0%      40%       Abstract interface
──────────────────────────────────────────────────────────────
TOTAL                      25%    60-70%
```

## Testing Pyramid

```
              E2E Tests (Manual)
            /                    \
       Integration Tests
      /                        \
   Unit Tests (Mocked I/O)
  /                            \
Fast, Many                      Slow, Few
```

### Unit Tests (Current: 48 tests)

**What we test:**
- ✅ Configuration parsing and validation
- ✅ Worktree path calculations
- ✅ Port allocation logic
- ✅ Agent status determination
- ✅ Template slug generation
- ✅ File operations (mocked)
- ✅ Git operations (mocked)

**What we DON'T unit test:**
- ❌ Actual tmux sessions
- ❌ Real git operations
- ❌ GitHub API calls
- ❌ Container runtime execution

### Integration Tests (Planned)

Not yet implemented. Future additions:

```bash
# tests/integration/test_cli.py
def test_init_command(tmp_project):
    """Test agenttree init creates proper structure."""
    result = runner.invoke(cli, ["init"])
    assert result.exit_code == 0
    assert (tmp_project / ".agenttree.yaml").exists()

# tests/integration/test_github.py
@pytest.mark.requires_gh_cli
def test_create_issue_pr_flow(test_repo):
    """Test full GitHub workflow."""
    # Requires actual GitHub test repo
```

### E2E Tests (Manual)

Documented workflows to test manually:

1. **Fresh project setup**
   ```bash
   mkdir test-project && cd test-project
   git init
   agenttree init
   agenttree setup 1
   ```

2. **Issue start**
   ```bash
   agenttree start 1 42
   agenttree attach 1  # Verify agent got task
   ```

3. **Notes management**
   ```bash
   agenttree notes show 1
   agenttree notes search "auth"
   agenttree notes archive 1
   ```

## Module-Specific Strategies

### config.py (Current: 96%, Target: 98%)

**Testing approach:**
```python
# Unit tests for all parsing logic
def test_config_from_dict():
    config = Config.model_validate({...})
    assert config.project == "myapp"

# Edge cases
def test_invalid_port_range():
    with pytest.raises(ValidationError):
        Config(port_range="invalid")
```

**Missing coverage:**
- Line 123: `find_config_file()` edge case (no parent dirs)
- Line 134: Error message formatting

**Recommendation:** ✅ Current coverage is sufficient. Edge cases are minor.

### worktree.py (Current: 88%, Target: 90%)

**Testing approach:**
```python
# Mock subprocess.run for all git operations
@patch("subprocess.run")
def test_create_worktree(mock_run):
    manager.create_worktree(1)
    # Verify git commands called correctly
    assert "git worktree add" in str(mock_run.call_args)
```

**Missing coverage:**
- Lines 49-50: `WorktreeStatus` repr
- Lines 124-126: `is_busy()` error handling
- Lines 172, 261, 278-279: Error paths
- Lines 299, 307-308: List worktrees edge cases

**Recommendation:** ✅ Add 3-4 error handling tests to hit 90%.

### agents_repo.py (Current: 57%, Target: 80%)

**Testing approach:**
```python
# Mock file I/O and git operations
def test_create_task_file(tmp_path):
    agents_repo.agents_path = tmp_path / "agents"
    # Create template manually for test
    (tmp_path / "agents" / "templates").mkdir(parents=True)
    ...

# Test business logic directly
def test_slugify():
    assert slugify("Add Dark Mode") == "add-dark-mode"
```

**Missing coverage:**
- Lines 50-59: `_ensure_gh_cli()` - ✅ Already tested
- Lines 91-107: `_create_github_repo()` - ⚠️ Need mock tests
- Lines 122-142: `_clone_repo()` - ⚠️ Need mock tests
- Lines 146-182: `_initialize_structure()` - ⚠️ Integration test
- Lines 220-352: Template creation - ⚠️ Need tests
- Lines 393-451: Knowledge files - ⚠️ Need tests

**Recommendation:**
- ✅ Add tests for `_create_github_repo()` (mock gh CLI)
- ✅ Add tests for template content validation
- ❌ Skip `_initialize_structure()` (integration test territory)

**New tests needed:**
```python
def test_create_github_repo_new():
    """Test creating new GitHub repo."""
    with patch("subprocess.run") as mock:
        mock.side_effect = [
            Mock(returncode=1),  # gh repo view (doesn't exist)
            Mock(returncode=0),  # gh repo create (success)
        ]
        agents_repo._create_github_repo()
        # Verify gh repo create was called

def test_create_templates():
    """Test template file contents."""
    agents_repo._create_templates()

    template = (agents_repo.agents_path / "templates" / "feature-spec.md").read_text()
    assert "# {title}" in template
    assert "## Summary" in template
```

### github.py (Current: 0%, Target: 60%)

**Testing approach:**
```python
# Mock gh CLI calls
@patch("subprocess.run")
def test_get_issue(mock_run):
    mock_run.return_value = Mock(
        returncode=0,
        stdout='{"title": "Test", "body": "..."}'
    )
    issue = get_issue(42)
    assert issue.title == "Test"

# Test error handling
def test_get_issue_not_found(mock_run):
    mock_run.return_value = Mock(returncode=1)
    with pytest.raises(RuntimeError):
        get_issue(999)
```

**Recommendation:** ✅ Add mock-based unit tests for all public functions.

### tmux.py (Current: 0%, Target: 50%)

**Challenge:** Tmux operations require tmux server running.

**Testing approach:**
```python
# Option 1: Mock subprocess (unit tests)
@patch("subprocess.run")
def test_create_session(mock_run):
    create_session("test-session", Path("/tmp"))
    assert "tmux new-session" in str(mock_run.call_args)

# Option 2: Integration tests (requires tmux)
@pytest.mark.requires_tmux
def test_tmux_session_lifecycle():
    """Actual tmux test."""
    create_session("test", Path("/tmp"))
    assert session_exists("test")
    kill_session("test")
    assert not session_exists("test")
```

**Recommendation:**
- ✅ Add mock-based unit tests (30% coverage)
- ⏸️ Defer integration tests to Phase 3

### cli.py (Current: 0%, Target: 40%)

**Challenge:** Click CLI testing requires CliRunner integration tests.

**Testing approach:**
```python
from click.testing import CliRunner

def test_init_command():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(main, ["init", "--project", "test"])
        assert result.exit_code == 0
        assert Path(".agenttree.yaml").exists()

def test_status_command():
    # Requires mocked WorktreeManager
    with patch("agenttree.cli.WorktreeManager"):
        result = runner.invoke(main, ["status"])
        assert "Agent" in result.output
```

**Recommendation:**
- ✅ Add CliRunner tests for major commands
- ⏸️ Defer to Phase 3 (not blocking)

### container.py (Current: 0%, Target: 30%)

**Challenge:** Platform-specific, requires Docker/Podman/Apple Container.

**Testing approach:**
```python
# Test detection logic only
@patch("shutil.which")
@patch("platform.system")
def test_detect_container_macos(mock_system, mock_which):
    mock_system.return_value = "Darwin"
    mock_which.side_effect = lambda cmd: "/usr/bin/container" if cmd == "container" else None

    runtime = detect_container_runtime()
    assert runtime == "apple-container"

# Skip actual execution
@pytest.mark.skip("Requires Docker")
def test_run_in_docker():
    ...
```

**Recommendation:**
- ✅ Test detection logic only (30% coverage)
- ❌ Skip execution tests (not worth CI complexity)

### agents/base.py (Current: 0%, Target: 40%)

**Testing approach:**
```python
# Test concrete implementations
class TestClaudeAgent:
    def test_start_command():
        agent = ClaudeAgent(config, 1)
        cmd = agent.get_start_command(Path("/worktree"))
        assert "claude" in cmd
        assert "--task" in cmd
```

**Recommendation:** ✅ Add tests for Claude and Aider adapters.

## Test Organization

```
tests/
├── unit/                      # Fast, mocked tests
│   ├── test_config.py         # ✅ 16 tests
│   ├── test_worktree.py       # ✅ 18 tests
│   ├── test_agents_repo.py    # ✅ 14 tests
│   ├── test_github.py         # ⏸️ TODO
│   ├── test_tmux.py           # ⏸️ TODO
│   ├── test_container.py      # ⏸️ TODO
│   └── test_agents.py         # ⏸️ TODO
│
├── integration/               # Slower, real operations
│   ├── test_cli.py            # ⏸️ Phase 3
│   ├── test_github_flow.py    # ⏸️ Phase 3
│   └── test_tmux_flow.py      # ⏸️ Phase 3
│
└── e2e/                       # Manual test scripts
    ├── test_fresh_setup.sh
    ├── test_dispatch_flow.sh
    └── test_notes_commands.sh
```

## CI Configuration

Currently no CI. Future:

```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --all-extras
      - run: uv run pytest tests/unit -v --cov=agenttree
      - run: uv run pytest tests/integration -v  # If added
```

## Running Tests

```bash
# All unit tests
uv run pytest tests/unit -v

# With coverage
uv run pytest tests/unit --cov=agenttree --cov-report=term-missing

# Specific module
uv run pytest tests/unit/test_config.py -v

# With coverage threshold (future)
uv run pytest --cov=agenttree --cov-fail-under=60
```

## Next Steps

### Phase 2 Completion
- [ ] Add tests for `github.py` (60% coverage)
- [ ] Add tests for `agents_repo.py` template creation (80% coverage)
- [ ] Add tests for `agents/` adapters (40% coverage)
- [ ] Document E2E test scenarios

### Phase 3
- [ ] Add integration tests for CLI commands
- [ ] Add integration tests for GitHub flow
- [ ] Set up GitHub Actions CI
- [ ] Add coverage badges to README

### Nice to Have
- [ ] Property-based testing (hypothesis) for edge cases
- [ ] Mutation testing (mutmut) to verify test quality
- [ ] Performance benchmarks (pytest-benchmark)

## Test Quality Guidelines

**Good test:**
```python
def test_get_port_for_agent_within_range():
    """Test port allocation within configured range."""
    config = Config(port_range="8001-8003")
    assert config.get_port_for_agent(1) == 8001
    assert config.get_port_for_agent(2) == 8002
    assert config.get_port_for_agent(3) == 8003
```

**Better test:**
```python
def test_get_port_for_agent_boundary_conditions():
    """Test port allocation at range boundaries."""
    config = Config(port_range="8001-8003")

    # Within range
    assert config.get_port_for_agent(1) == 8001

    # At boundary
    assert config.get_port_for_agent(3) == 8003

    # Out of range
    with pytest.raises(ValueError, match="out of range"):
        config.get_port_for_agent(4)
```

**Characteristics:**
- ✅ Clear test name describes what's tested
- ✅ Tests boundary conditions
- ✅ Verifies error handling
- ✅ Uses specific assertions
- ✅ Readable (no complex setup)

## Anti-Patterns to Avoid

❌ **Testing implementation details:**
```python
# Bad: Tests internal method
def test_internal_parse_method():
    result = config._parse_port_range("8001-8003")
    assert result == (8001, 8003)
```

❌ **Brittle mocks:**
```python
# Bad: Too specific, breaks on refactor
mock_run.assert_called_with(
    ["git", "worktree", "add", "/exact/path", "-b", "exact-branch"],
    cwd="/exact/cwd",
    check=True,
    capture_output=True
)
```

❌ **Testing multiple things:**
```python
# Bad: Tests create + list + delete in one test
def test_worktree_operations():
    create_worktree(1)
    assert len(list_worktrees()) == 1
    remove_worktree(1)
    assert len(list_worktrees()) == 0
```

✅ **Better approaches:**
- Test public interfaces only
- Use flexible mock assertions
- One concept per test
- Test behavior, not implementation

## Resources

- [pytest documentation](https://docs.pytest.org/)
- [unittest.mock guide](https://docs.python.org/3/library/unittest.mock.html)
- [Testing Click applications](https://click.palletsprojects.com/en/8.1.x/testing/)
- [Effective Python Testing](https://realpython.com/python-testing/)
