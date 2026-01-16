# Worktree Access to _agenttree

## Problem

Agents run in git worktrees (e.g., `.worktrees/issue-069-xxx/`). The `_agenttree/` folder contains:
- Issue definitions (`issues/`)
- Skill templates (`skills/`)
- Workflow instructions

But `_agenttree/` is gitignored (it's a separate git repo), so worktrees get an empty directory. Agents can't read their task instructions or update issue state.

## Options Evaluated

### Option 1: Symlinks (Rejected)

**Approach:** Create symlink in each worktree pointing to main repo's `_agenttree/`.

```bash
ln -s /path/to/main/_agenttree worktree/_agenttree
```

**Pros:**
- Simple to implement
- Transparent to code - just works

**Cons:**
- **Symlinks get committed to git** - shows up in PR diffs as changed files
- Causes confusion about what files agent actually changed
- Absolute paths in symlinks are machine-specific
- Requires cleanup when worktrees are removed

**Verdict:** Rejected. The git tracking issue is a dealbreaker.

---

### Option 2: Path Resolution via Git Worktree Linkage (Current)

**Approach:** Modify `get_agenttree_path()` to detect worktrees and find main repo.

```python
def get_agenttree_path() -> Path:
    cwd = Path.cwd()
    local_path = cwd / "_agenttree"

    # If local has content, use it
    if local_path.exists() and (local_path / "issues").exists():
        return local_path

    # In worktree, .git is a file with "gitdir: /path/to/main/.git/worktrees/xxx"
    git_path = cwd / ".git"
    if git_path.is_file():
        content = git_path.read_text().strip()
        if content.startswith("gitdir:"):
            gitdir = Path(content.split(":", 1)[1].strip())
            main_repo = gitdir.parent.parent.parent  # Up from .git/worktrees/xxx
            main_agenttree = main_repo / "_agenttree"
            if main_agenttree.exists():
                return main_agenttree

    return local_path
```

**Pros:**
- No files to commit - pure code solution
- Uses git's own worktree linkage
- Works transparently for all code using `get_agenttree_path()`

**Cons:**
- Agents use their worktree's agenttree code version (may be stale)
- Requires restart to pick up agenttree code changes

**Verdict:** Good solution. Stale code is acceptable - just restart agents for updates.

---

### Option 3: Global agenttree Installation

**Approach:** Install agenttree globally, agents use installed version.

```bash
# On main, after pull:
uv tool install .

# Agents use:
agenttree next  # (not "uv run agenttree next")
```

**Pros:**
- All agents use same agenttree version
- No path resolution needed
- Updates propagate to all agents immediately

**Cons:**
- Agents run in containers - can't access host's global install
- Would need to install in each container image
- Version conflicts if different agents need different versions
- More complex deployment

**Verdict:** Doesn't work well with containerized agents.

---

### Option 4: Mount _agenttree into Containers

**Approach:** When starting container, mount main repo's `_agenttree/` as a volume.

```bash
container run -v /path/to/main/_agenttree:/workspace/_agenttree ...
```

**Pros:**
- Clean separation
- No code changes needed
- Container sees real `_agenttree` contents

**Cons:**
- Requires container runtime changes
- Mount paths are machine-specific
- May have permission issues

**Verdict:** Viable but requires container infrastructure changes.

---

### Option 5: Copy _agenttree on Worktree Creation

**Approach:** Copy `_agenttree/` contents (not symlink) when creating worktree.

```python
shutil.copytree(main_agenttree, worktree_agenttree)
```

**Pros:**
- No symlinks
- Each worktree has its own copy

**Cons:**
- Copies get stale immediately
- Changes in worktree don't sync back to main
- Wastes disk space
- Agents would modify copies, not the real issues

**Verdict:** Rejected. Stale copies and sync issues make this unworkable.

---

## Recommendation

**Option 2: Path Resolution via Git Worktree Linkage**

This is the cleanest solution because:

1. **No artifacts** - Nothing gets committed to git
2. **Transparent** - Code using `get_agenttree_path()` works without changes
3. **Predictable** - Agents use code from when they started
4. **Simple recovery** - Restart agents to pick up changes

The downside (stale agenttree code) is acceptable:
- Most agenttree changes don't affect running agents
- When changes matter, restart affected agents
- This is explicit and predictable

### Implementation Status

- [x] `get_agenttree_path()` updated to find main repo's `_agenttree`
- [x] Symlink creation code removed from `cli.py`
- [x] Existing symlinks cleaned up from worktrees
- [x] `.gitignore` updated to ignore `_agenttree` (symlinks too)

### Future Consideration

If container mounting (Option 4) becomes needed, it's a clean addition that doesn't conflict with Option 2. The path resolution handles both cases - if `_agenttree` exists locally (mounted), use it; otherwise, find it via git linkage.
