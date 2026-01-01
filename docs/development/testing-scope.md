# Testing Scope Definition

**Purpose:** Define clear boundaries for what AgentTree WILL and will NOT test.
**Goal:** Achieve 100% coverage of all in-scope code.
**Last Updated:** 2026-01-01

## Philosophy

Test **business logic and data transformations**. Skip **external I/O that would require heavy integration testing**.

- ✅ **Test:** Pure functions, algorithms, validation, state management
- ❌ **Skip:** Actual external systems (GitHub API, tmux, Docker, file I/O)
- 🎯 **Mock:** External calls when testing business logic that depends on them

## Module-by-Module Scope

### ✅ config.py - 100% Coverage Required

**What we WILL test:**
- ✅ All Pydantic model validation
- ✅ Default values
- ✅ Port allocation logic
- ✅ Path calculations
- ✅ YAML parsing (with mocked file reads)
- ✅ Config file discovery logic

**What we will NOT test:**
- ❌ Nothing - this module is pure business logic

**Current Coverage:** 96% → **Target: 100%**

**Missing Lines:**
- Line 123: `find_config_file()` - when no config found in any parent
- Line 134: Error message formatting edge case

**Action:** Add 2 tests for edge cases.

---

### ✅ worktree.py - 100% Coverage Required

**What we WILL test:**
- ✅ Worktree path calculations
- ✅ Busy detection logic
- ✅ Git command construction (mocked subprocess)
- ✅ Status object creation
- ✅ Error handling for git failures
- ✅ Branch name validation

**What we will NOT test:**
- ❌ Actual git operations (tested via mocks)
- ❌ Real filesystem changes

**Current Coverage:** 88% → **Target: 100%**

**Missing Lines:**
- Lines 49-50: `WorktreeStatus.__repr__()` - string representation
- Lines 124-126: `is_busy()` error handling when git status fails
- Line 172: `create_worktree()` error path
- Line 261: `remove_worktree()` when worktree doesn't exist
- Lines 278-279: `reset_worktree()` error handling
- Line 299: `list_worktrees()` parsing errors
- Lines 307-308: `get_agent_status()` edge cases

**Action:** Add 8 tests for error paths and edge cases.

---

### ✅ agents_repo.py - 100% Coverage Required

**What we WILL test:**
- ✅ Repository creation logic (mocked gh CLI)
- ✅ Folder structure creation
- ✅ Template content validation
- ✅ Spec/task file creation
- ✅ Archive logic
- ✅ Slug generation
- ✅ Gitignore management
- ✅ All helper methods

**What we will NOT test:**
- ❌ Actual GitHub API calls (mocked via gh CLI)
- ❌ Actual git clone operations (mocked)
- ❌ Real file I/O (use tmp_path)

**Current Coverage:** 57% → **Target: 100%**

**Missing Lines:**
- Lines 50-59: `_ensure_gh_cli()` - ✅ Already tested
- Lines 91-107: `_create_github_repo()` - needs tests
- Lines 122-142: `_clone_repo()` - needs tests
- Lines 146-182: `_initialize_structure()` - needs tests
- Lines 186-187: `_create_readme()` - needs tests
- Lines 220-352: Template creation methods - needs tests
- Lines 393-451: Knowledge file creation - needs tests
- Line 491: `create_spec_file()` commit error handling
- Lines 560-573: `create_task_file()` template reading
- Lines 590-614: Task file template formatting
- Lines 627-652: Spec file formatting
- Lines 662-678: Archive logic edge cases
- Line 693: `archive_task()` when no tasks exist - ✅ Already tested
- Lines 720-726: `_commit()` error handling

**Action:** Add ~20 tests for template creation, formatting, and error paths.

---

### ✅ github.py - 100% Coverage Required

**What we WILL test:**
- ✅ All gh CLI command construction
- ✅ JSON parsing from gh output
- ✅ Error handling for failed gh commands
- ✅ Issue/PR data extraction
- ✅ URL construction
- ✅ Authentication checks

**What we will NOT test:**
- ❌ Actual GitHub API calls (mocked gh CLI subprocess)
- ❌ Real network operations

**Current Coverage:** 0% → **Target: 100%**

**Action:** Add ~15 tests covering all public functions with mocked subprocess calls.

---

### ❌ tmux.py - EXCLUDED from Scope

**Why excluded:**
- Requires actual tmux server running
- Integration test territory, not unit tests
- Mocking tmux would test mocks, not logic
- Better tested manually or in Phase 3 integration tests

**Decision:** Mark as "Integration Test Required" - skip unit tests entirely.

**Target Coverage:** 0% (intentionally excluded)

---

### ❌ container.py - EXCLUDED from Scope

**Why excluded:**
- Platform-specific (macOS/Linux/Windows)
- Requires Docker/Podman/Apple Container installed
- Detection logic is trivial (`shutil.which()` calls)
- Execution testing would require containers running

**What we WILL test (minimal):**
- ✅ Container runtime detection logic only (~30 lines)

**What we will NOT test:**
- ❌ Actual container execution
- ❌ Platform-specific behavior

**Target Coverage:** ~30% (detection logic only)

**Action:** Add 3-4 tests for detection logic.

---

### ❌ cli.py - EXCLUDED from Scope

**Why excluded:**
- Click framework testing requires CliRunner (integration tests)
- CLI tests are better as end-to-end tests
- Business logic is in other modules (already tested)
- Deferred to Phase 3 integration test suite

**Decision:** Phase 3 will add integration tests using Click's CliRunner.

**Target Coverage:** 0% (intentionally excluded, Phase 3)

---

### ⚠️ agents/base.py - PARTIAL Coverage

**What we WILL test:**
- ✅ ClaudeAgent command construction
- ✅ AiderAgent command construction
- ✅ BaseAgent interface (abstract methods raise NotImplementedError)
- ✅ Custom agent configuration

**What we will NOT test:**
- ❌ Actual agent execution (integration test)

**Current Coverage:** 0% → **Target: 60%**

**Action:** Add 6-8 tests for agent adapters.

---

## Summary Table

| Module | Current | Target | Rationale |
|--------|---------|--------|-----------|
| **config.py** | 96% | **100%** | Pure business logic |
| **worktree.py** | 88% | **100%** | Core functionality |
| **agents_repo.py** | 57% | **100%** | Core functionality |
| **github.py** | 0% | **100%** | Mock gh CLI calls |
| **agents/base.py** | 0% | **60%** | Test adapters, skip execution |
| **container.py** | 0% | **30%** | Detection logic only |
| **tmux.py** | 0% | **0%** | ❌ Excluded - integration tests |
| **cli.py** | 0% | **0%** | ❌ Excluded - Phase 3 |
| **__init__.py** | 100% | **100%** | Already complete |

## Overall Target

**Weighted Coverage Target: 75%**

Calculation:
```
In-scope lines: config + worktree + agents_repo + github + agents/base + container
= 50 + 89 + 146 + 99 + 48 + 57 = 489 lines

Target in-scope:
= 50 + 89 + 146 + 99 + 29 (60% of 48) + 17 (30% of 57) = 430 lines

Out-of-scope lines: tmux + cli + agents/__init__
= 86 + 252 + 0 = 338 lines

Total lines: 489 + 338 = 827 lines
Coverage: 430/827 = 52% overall (but 100% of defined scope)
```

**Key Metric: 100% of testable business logic**

## Test Organization

```
tests/
├── unit/
│   ├── test_config.py           ✅ 100% of config.py
│   ├── test_worktree.py         ✅ 100% of worktree.py
│   ├── test_agents_repo.py      ✅ 100% of agents_repo.py
│   ├── test_github.py           ✅ 100% of github.py
│   ├── test_agents.py           ✅ 60% of agents/base.py
│   └── test_container.py        ✅ 30% of container.py (detection only)
│
└── integration/  (Phase 3)
    ├── test_cli.py              ⏸️ CLI commands with CliRunner
    ├── test_tmux.py             ⏸️ Actual tmux operations
    └── test_e2e.py              ⏸️ Full workflows
```

## Testing Principles

### DO Test

1. **Pure Functions**
   ```python
   ✅ def slugify(text: str) -> str:
       """Convert text to slug - pure transformation"""
   ```

2. **Business Logic**
   ```python
   ✅ def is_busy(worktree_path: Path) -> bool:
       """Busy detection logic - testable with mocks"""
   ```

3. **Data Validation**
   ```python
   ✅ class Config(BaseModel):
       """Pydantic validation - unit testable"""
   ```

4. **Command Construction**
   ```python
   ✅ def build_git_command(branch: str) -> List[str]:
       """Command building - test the list, mock subprocess"""
   ```

### DON'T Test

1. **External Systems**
   ```python
   ❌ subprocess.run(["tmux", "new-session"])
      # Don't run actual tmux - mock subprocess.run
   ```

2. **File I/O (use fixtures)**
   ```python
   ❌ Path("/real/path").write_text("data")
      # Don't write real files

   ✅ tmp_path / "file.txt"  # Use pytest tmp_path
   ```

3. **Framework Internals**
   ```python
   ❌ Click's argument parsing
      # Don't test Click framework - trust it works
   ```

4. **Platform Behavior**
   ```python
   ❌ Docker container execution
      # Don't test Docker - mock shutil.which()
   ```

## Success Criteria

- ✅ All in-scope modules at 100% coverage
- ✅ All business logic tested
- ✅ All error paths tested
- ✅ All edge cases tested
- ✅ Zero untested business logic
- ✅ Clear boundaries documented
- ✅ Fast test suite (<5 seconds)

## Running Tests

```bash
# All unit tests
pytest tests/unit -v

# With coverage report (excludes tmux/cli)
pytest tests/unit --cov=agenttree \
    --cov-report=term-missing \
    --cov-report=html

# Verify 100% of in-scope code
pytest tests/unit \
    --cov=agenttree.config \
    --cov=agenttree.worktree \
    --cov=agenttree.agents_repo \
    --cov=agenttree.github \
    --cov-fail-under=100
```

## Maintenance

When adding new code:

1. **Ask: Is this testable business logic?**
   - YES → Add unit tests, aim for 100%
   - NO → Mark as integration test, document why

2. **Update this document** if scope changes

3. **Keep tests fast** - mock external calls

4. **One test per behavior** - not per function

## Exclusion Justifications

### Why exclude tmux.py?

**Integration test nature:**
- Requires tmux server
- Tests real session management
- Better tested with actual tmux running
- Mocks would be meaningless (testing mocks, not code)

**Phase 3 approach:**
- Docker container with tmux installed
- Integration test suite
- Real session creation/destruction
- Better coverage than mocked unit tests

### Why exclude cli.py?

**Click framework complexity:**
- CliRunner provides integration testing
- Business logic is in other modules
- Click handles argument parsing (trust framework)
- Better tested as end-to-end workflows

**Phase 3 approach:**
- CliRunner-based integration tests
- Test actual command execution
- Verify output formatting
- Test error messages

### Why partial coverage on container.py?

**Platform-specific:**
- Different behavior on macOS/Linux/Windows
- Requires Docker/Podman installed
- Execution needs real containers

**What we test:**
- Detection logic (which runtime exists)
- Platform identification
- Command construction

**What we skip:**
- Actual container execution
- Platform-specific behavior
- Container runtime quirks

---

**This document is the contract:** We commit to 100% coverage of everything in scope, and explicitly exclude integration-test territory.
