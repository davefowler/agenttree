# AgentTree Edge Cases & Test Coverage

This document tracks all edge cases, error conditions, and special states in the AgentTree system, along with their test coverage status.

## Legend

- **Unit**: Has unit test coverage
- **Integration**: Has integration test coverage
- **Handling**: How the edge case is currently handled
- **Priority**: P0 (critical), P1 (important), P2 (nice-to-have)

---

## 1. Sync & Concurrency

### 1.1 File Lock Contention
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| Two agents sync simultaneously | ❌ | ❌ | `fcntl.flock()` with `LOCK_NB`, returns False | P1 |
| Lock file never released (process crash) | ❌ | ❌ | Lock auto-releases on fd close | P2 |
| Lock timeout during state operations | ❌ | ❌ | 5-second timeout, exception propagates | P2 |
| Sync called recursively (from hooks) | ❌ | ❌ | `controller_hooks_executed` flag breaks loop | P1 |

### 1.2 YAML File Race Conditions
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| Concurrent issue.yaml writes | N/A | N/A | **NON-ISSUE BY DESIGN** - agents never write issue.yaml, controller only writes at human gates when agent is paused | - |
| Concurrent state.yaml writes | ❌ | ❌ | File lock protects | P2 |
| Write interrupted mid-file | ❌ | ❌ | Rare, recoverable | P2 |
| YAML file corrupted/invalid | ❌ | ❌ | Silent skip in list_issues | P2 |

**See `docs/concurrency_design.md` for full analysis of why concurrent writes are non-issues.**

---

## 2. Git Operations

### 2.1 Rebase Scenarios
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| Clean rebase succeeds | ✅ | ❌ | Normal flow | P0 |
| Rebase with merge conflicts | ❌ | ❌ | Aborts rebase, returns False | P0 |
| Uncommitted changes before rebase | ✅ | ❌ | Auto-commit first | P0 |
| Rebase abort fails | ❌ | ❌ | **NOT HANDLED** - leaves broken state | P1 |
| Remote branch deleted | ❌ | ❌ | Fetch fails, operation fails | P2 |

### 2.2 Merge Conflicts
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| Merge conflict during _agenttree sync | N/A | N/A | **NON-ISSUE BY DESIGN** - single sync process, agents can't push, different agents write different files | - |
| Merge conflict during PR merge (user's repo) | ❌ | ❌ | gh merge fails, human must resolve | P2 |
| Stash-pop conflict | ❌ | ❌ | Single attempt, no recovery | P2 |

**Note:** _agenttree conflicts are non-issues because only the host syncs and agents write to sharded issue folders.

### 2.3 Push Operations
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| Push succeeds | ✅ | ❌ | Normal flow | P0 |
| Push rejected (non-fast-forward) | ❌ | ❌ | Falls back to `--force-with-lease` | P1 |
| Push rejected (branch protection) | ❌ | ❌ | **NOT HANDLED** | P2 |
| Remote not configured | ❌ | ❌ | Returns False gracefully | P1 |
| Network offline | ❌ | ❌ | "Could not resolve host" detected | P1 |

### 2.4 Worktree Operations
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| Create worktree succeeds | ✅ | ❌ | Normal flow | P0 |
| Worktree already exists (restart) | ✅ | ❌ | Reuses existing | P0 |
| Worktree path doesn't exist | ❌ | ❌ | Fallback path guessing | P1 |
| Branch already exists | ✅ | ❌ | Reuses branch | P1 |
| Reset worktree (destructive) | ❌ | ❌ | Hard reset + clean | P2 |

---

## 3. GitHub/PR Operations

### 3.1 PR Creation
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| PR created successfully | ✅ | ❌ | Normal flow | P0 |
| PR already exists | ✅ | ❌ | Extracts PR# from error message | P0 |
| gh CLI not installed | ❌ | ❌ | RuntimeError raised | P1 |
| gh CLI not authenticated | ❌ | ❌ | RuntimeError raised | P1 |
| Auto-commit before PR | ✅ | ❌ | Commits uncommitted changes | P0 |

### 3.2 PR Approval
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| PR approved by reviewer | ✅ | ❌ | Normal flow | P0 |
| Self-approval blocked | ✅ | ❌ | Shows `--skip-approval` message | P0 |
| PR not found | ❌ | ❌ | Error propagates | P1 |
| API rate limited | ❌ | ❌ | **NOT HANDLED** | P2 |

### 3.3 PR Merge
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| PR merged successfully | ✅ | ❌ | Normal flow | P0 |
| PR merged externally (GitHub UI) | ✅ | ❌ | `check_merged_prs()` detects | P0 |
| PR has merge conflicts | ❌ | ❌ | **NOT HANDLED** - merge fails | P0 |
| PR closed without merge | ❌ | ❌ | Not detected | P2 |
| CI checks failing | ❌ | ❌ | **NOT HANDLED** - merge may fail | P1 |

### 3.4 CI/Checks
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| CI passes | ❌ | ❌ | wait_for_ci returns True | P1 |
| CI fails | ❌ | ❌ | **NOT HANDLED** - agent stuck at implementation_review | P0 |
| CI timeout | ❌ | ❌ | Returns False after timeout | P1 |
| No CI checks configured | ❌ | ❌ | Keeps polling (risky) | P2 |

**Issue 088 filed:** CI failure feedback loop - need to notify agent when PR checks fail.

---

## 4. Stage Transitions

### 4.1 Normal Transitions
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| backlog → define | ✅ | ❌ | Start command | P0 |
| define → research | ✅ | ❌ | next command | P0 |
| research → plan | ✅ | ❌ | next command | P0 |
| plan → plan_assess | ✅ | ❌ | next command | P0 |
| plan_assess → plan_revise | ✅ | ❌ | next command | P0 |
| plan_revise → plan_review | ✅ | ❌ | next command | P0 |
| plan_review → implement | ✅ | ❌ | approve command (host) | P0 |
| implement substages | ✅ | ❌ | next command | P0 |
| implementation_review → accepted | ✅ | ❌ | approve command (host) | P0 |

### 4.2 Human Review Gates
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| Agent blocked at plan_review | ❌ | ❌ | human_review: true | P0 |
| Agent blocked at implementation_review | ❌ | ❌ | human_review: true | P0 |
| Host can approve plan_review | ❌ | ❌ | approve command | P0 |
| Host can approve implementation_review | ❌ | ❌ | approve command | P0 |

### 4.3 Terminal States
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| Cannot advance from accepted | ✅ | ❌ | terminal: true | P1 |
| Cannot advance from not_doing | ✅ | ❌ | terminal: true | P1 |
| Move to not_doing cleans up agent | ❌ | ❌ | cleanup_issue_agent called | P1 |

---

## 5. Hook Validation

### 5.1 File Validators
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| file_exists - file present | ✅ | ❌ | Passes | P0 |
| file_exists - file missing | ✅ | ❌ | Returns error, blocks | P0 |
| section_check - section exists | ✅ | ❌ | Passes | P0 |
| section_check - section missing | ✅ | ❌ | Returns error, blocks | P0 |
| section_check - h2 vs h3 headers | ✅ | ❌ | Accepts both ## and ### | P1 |
| section_check - all_checked | ✅ | ❌ | Verifies checkboxes | P0 |

### 5.2 Field Validators
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| field_check - meets minimum | ✅ | ❌ | Passes | P0 |
| field_check - below minimum | ✅ | ❌ | Returns error, blocks | P0 |
| field_check - YAML block missing | ✅ | ❌ | Returns error | P1 |
| field_check - nested path missing | ✅ | ❌ | Returns error | P1 |
| min_words - enough words | ✅ | ❌ | Passes | P1 |
| min_words - too few words | ✅ | ❌ | Returns error | P1 |
| has_list_items - has items | ✅ | ❌ | Passes | P1 |
| has_list_items - no items | ✅ | ❌ | Returns error | P1 |
| contains - value present | ✅ | ❌ | Passes | P1 |
| contains - value missing | ✅ | ❌ | Returns error | P1 |

### 5.3 Git Validators
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| has_commits - has commits | ✅ | ❌ | Passes | P0 |
| has_commits - no commits | ✅ | ❌ | Returns error, blocks | P0 |
| pr_approved - is approved | ✅ | ❌ | Passes | P0 |
| pr_approved - not approved | ✅ | ❌ | Returns error, blocks | P0 |

### 5.4 Command Hooks
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| Command succeeds | ✅ | ❌ | Passes | P0 |
| Command fails (non-zero exit) | ✅ | ❌ | Returns error | P0 |
| Command timeout | ✅ | ❌ | Returns error | P1 |
| Host-only hook in container | ✅ | ❌ | Skipped silently | P0 |
| Optional hook fails | ✅ | ❌ | Skipped | P1 |

---

## 6. Agent/Container Management

### 6.1 Container Lifecycle
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| Container starts successfully | ✅ | ❌ | Normal flow | P0 |
| Container runtime not found | ✅ | ❌ | Preflight check fails | P0 |
| Apple Container not running | ❌ | ❌ | Returns False, warning | P1 |
| Docker not running | ❌ | ❌ | Attempts start on macOS | P1 |
| Container crashes mid-operation | ❌ | ❌ | **NOT HANDLED** | P1 |

### 6.2 Agent Communication
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| Send message to agent | ❌ | ❌ | tmux send-keys | P0 |
| Agent not running | ❌ | ❌ | Session doesn't exist | P0 |
| Agent not responding | ❌ | ❌ | **NOT HANDLED** - just sends | P1 |
| tmux session dead | ❌ | ❌ | send_keys raises exception | P1 |
| Message too long | ❌ | ❌ | **NOT HANDLED** | P2 |

### 6.3 Port Allocation
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| Port allocated successfully | ✅ | ❌ | Normal flow | P0 |
| Port already in use | ❌ | ❌ | Skips to next port | P1 |
| All ports exhausted | ❌ | ❌ | **INFINITE LOOP** | P0 |
| Port freed on cleanup | ❌ | ❌ | Removes from allocated list | P1 |

### 6.4 Agent Cleanup
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| Cleanup on accepted | ❌ | ❌ | cleanup_agent hook | P0 |
| Cleanup on not_doing | ❌ | ❌ | cleanup_issue_agent called | P0 |
| Orphaned agent on web move | ❌ | ❌ | Web endpoint calls cleanup | P1 |
| Cleanup fails (process hung) | ❌ | ❌ | **NOT HANDLED** | P1 |

---

## 7. Multi-Issue Scenarios

### 7.1 Dependencies
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| Issue blocked by dependency | ✅ | ❌ | Checks dependency stage | P1 |
| Dependency resolved | ❌ | ❌ | start_blocked_issues hook | P1 |
| Circular dependency | ❌ | ❌ | **NOT DETECTED** | P1 |
| Missing dependency issue | ✅ | ❌ | Treated as unmet | P1 |

### 7.2 Concurrent Operations
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| Two issues modify same file | ❌ | ❌ | **NOT HANDLED** - conflict at merge | P2 |
| Two agents run agenttree next | ❌ | ❌ | File lock for sync only | P1 |
| Agent and host run simultaneously | ❌ | ❌ | Partial protection via locks | P1 |

---

## 8. Error Recovery

### 8.1 Hook Failures
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| Hook fails, state preserved | ❌ | ❌ | Validation before transition | P0 |
| Multiple hooks, one fails | ✅ | ❌ | All errors collected | P0 |
| Hook timeout | ✅ | ❌ | Returns error | P1 |
| Partial hook execution | ❌ | ❌ | **NO ROLLBACK** | P1 |

### 8.2 State Recovery
| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| Issue stuck in bad state | ❌ | ❌ | Manual YAML edit | P2 |
| Agent died, issue still assigned | ❌ | ❌ | Can restart with `agenttree start` | P1 |
| PR number mismatch | ❌ | ❌ | **NOT HANDLED** | P2 |

---

## 9. Content Validation (By Design - Agent Must Fix)

| Edge Case | Unit | Integration | Handling | Priority |
|-----------|------|-------------|----------|----------|
| Review score < 7 | ✅ | ❌ | Blocks at implement.wrapup | P0 |
| Critical issues not empty | ✅ | ❌ | Blocks at implement.feedback | P0 |
| Self-review checklist unchecked | ✅ | ❌ | Blocks at code_review | P0 |
| Required section empty | ✅ | ❌ | Blocks at relevant stage | P0 |
| Missing required file | ✅ | ❌ | Blocks at relevant stage | P0 |

---

## Test Coverage Summary

| Category | Unit Tests | Integration Tests | Critical Gaps |
|----------|------------|-------------------|---------------|
| Sync & Concurrency | 0/8 | 0/8 | Concurrent YAML writes |
| Git Operations | 6/15 | 0/15 | Merge conflicts |
| GitHub/PR | 6/14 | 0/14 | CI failures, merge conflicts |
| Stage Transitions | 12/14 | 0/14 | Human gates |
| Hook Validation | 22/24 | 0/24 | - |
| Agent/Container | 2/14 | 0/14 | Agent not responding, port exhaustion |
| Multi-Issue | 2/6 | 0/6 | Circular deps |
| Error Recovery | 2/6 | 0/6 | Partial rollback |
| Content Validation | 5/5 | 0/5 | - |

**Total: ~57 unit tests exist, 67 integration tests created (27 passing, 40 need API fixes)**

---

## Priority Implementation Order

### P0 - Must Have (Blocking Issues)
1. Full workflow happy path (integration)
2. Human review gates (integration)
3. Concurrent YAML write protection (unit + integration)
4. Port exhaustion fix + test (unit)
5. Merge conflict handling (integration)

### P1 - Should Have
6. Hook validation in workflow context (integration)
7. Agent not responding detection (unit + integration)
8. Rebase conflict recovery (integration)
9. CI check integration (integration)
10. Circular dependency detection (unit)

### P2 - Nice to Have
11. Branch protection handling
12. API rate limiting
13. Partial hook rollback
14. PR closed without merge detection
