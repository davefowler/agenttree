#!/usr/bin/env bash
#
# Bootstrap a fresh github.com/davefowler/stagent repo from the
# contents of this folder. Idempotent-ish: refuses to clobber an
# existing local target dir or an existing GH repo.
#
# Prereqs on your machine:
#   - gh (authenticated: `gh auth login`)
#   - git
#   - go 1.22+
#
# Usage:
#   ./setup-new-repo.sh [target-dir]
#
# Default target-dir: ~/stagent

set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_DIR="${1:-$HOME/stagent}"
GH_REPO="davefowler/stagent"
GO_MODULE="github.com/davefowler/stagent"

# ─── Prereq checks ────────────────────────────────────────────────────

for cmd in gh git go; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "✗ '$cmd' not found. Install it and re-run." >&2
    exit 1
  fi
done

if ! gh auth status >/dev/null 2>&1; then
  echo "✗ 'gh' is not authenticated. Run: gh auth login" >&2
  exit 1
fi

GO_VERSION=$(go version | awk '{print $3}' | sed 's/^go//')
GO_MAJOR=$(echo "$GO_VERSION" | cut -d. -f1)
GO_MINOR=$(echo "$GO_VERSION" | cut -d. -f2)
if [ "$GO_MAJOR" -lt 1 ] || { [ "$GO_MAJOR" -eq 1 ] && [ "$GO_MINOR" -lt 22 ]; }; then
  echo "✗ Go 1.22+ required; got $GO_VERSION" >&2
  exit 1
fi

if [ -e "$TARGET_DIR" ]; then
  echo "✗ Target already exists: $TARGET_DIR" >&2
  echo "  Remove it first or pass a different path: $0 /some/other/dir" >&2
  exit 1
fi

if gh repo view "$GH_REPO" >/dev/null 2>&1; then
  echo "✗ GH repo $GH_REPO already exists. Delete it on github.com or rename." >&2
  exit 1
fi

# ─── 1. Create the GH repo ───────────────────────────────────────────

echo "→ Creating github.com/$GH_REPO ..."
gh repo create "$GH_REPO" \
  --public \
  --description "Staged workflow for AI agents — event-sourced state machine driving Claude sessions through configurable stages" \
  --disable-wiki

# ─── 2. Copy source tree ──────────────────────────────────────────────

echo "→ Copying source to $TARGET_DIR ..."
mkdir -p "$TARGET_DIR"
# Copy everything except this bootstrap script and any local build output.
( cd "$SOURCE_DIR" && \
  tar --exclude='./setup-new-repo.sh' \
      --exclude='./site' \
      --exclude='./.git' \
      -cf - . ) | ( cd "$TARGET_DIR" && tar -xf - )

# ─── 3. Initialize Go module ──────────────────────────────────────────

cd "$TARGET_DIR"
echo "→ Initializing Go module $GO_MODULE ..."
go mod init "$GO_MODULE"

# Pin Go version explicitly.
sed -i.bak -E "s/^go [0-9]+\.[0-9]+/go 1.22/" go.mod && rm -f go.mod.bak

# ─── 4. CI workflow ───────────────────────────────────────────────────

mkdir -p .github/workflows
cat > .github/workflows/ci.yml <<'YAML'
name: ci

on:
  push:
    branches: [main]
  pull_request:

jobs:
  go:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with:
          go-version: '1.22'
          cache: true
      - name: vet
        run: go vet ./...
      - name: test
        run: go test ./...

  docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
      - name: install mkdocs
        run: pip install mkdocs mkdocs-material pymdown-extensions
      - name: build (strict)
        run: mkdocs build --strict
YAML

# ─── 5. IMPLEMENTING.md ───────────────────────────────────────────────

cat > IMPLEMENTING.md <<'MD'
# For the implementing agent

This repo was specified before any Go code was written. Your job is to
implement **v0.1** from the locked decisions in `notes/decisions.md`.

## Read in order (under 90 minutes)

1. **`notes/decisions.md`** — the contract. Locked decisions are
   non-negotiable without user approval. Tabled items are out of scope
   for v0.1.
2. **`notes/architecture.md`** — types, lifecycle, design rationale.
3. **`notes/schema.md`** — SQLite schema, event types, views.
4. **`notes/config.md`** — `.stagent.yaml` reference.

User-facing docs (`docs/`) cover the same material rendered for end
users. Read them only when `notes/` has a gap.

## v0.1 scope (decisions.md section 6)

**In:**

- Event log + schema + views + append-only triggers (WAL).
- Runner: heartbeat + task workers, PID file, SIGHUP reload, crash
  recovery via orphan-session detection.
- Stage types: `agent`, `script`.
- Hook slots: `enter`, `exit`.
- Hooks: `run_shell`, `section_check`, `min_words`,
  `validate_task_sections`.
- CLI: `init`, `new`, `run`, `status`, `list`, `show`, `log`, `goto`,
  `abort`, `session`, `restart`.
- Default flow: `setup → code → cleanup` (the scaffold's slim flow).
- Section-path parser: literal segments + regex `/.../[N]`.
- `cmd/fraude/` mock-claude binary for tests.

**Out (deferred to v0.2 / v0.3):**

- `human` stage type. `tick` hooks. `wait_for_*` / `ci_status`.
- `pr`, `review`, `human_review` stages in the default flow.
- SwiftUI viewer. `commands:` user recipes. `force_tick` /
  `stagent poll`.

## Build order suggestion

1. `go.mod` is done; layout per `notes/decisions.md` section 12.
2. `internal/events/` — schema, append, replay. Unit-tested with raw SQL.
3. `internal/sections/` — markdown path parser + matcher. Pure logic;
   easy to test exhaustively.
4. `internal/config/` — YAML load, struct validation.
5. `internal/hooks/` — interface + the four v0.1 hooks.
6. `internal/runner/` — heartbeat, task worker, `claude` subprocess.
7. `cmd/fraude/` — mock claude (decisions.md section 5).
8. `cmd/stagent/` — CLI subcommands via cobra.
9. End-to-end test: `stagent init` → write task → `stagent run` → task
   completes (using fraude scripted responses).

## House rules

- Libraries per decisions.md section 13. Don't reach for alternatives.
- Go 1.22+ (decisions.md section 14).
- Tests live alongside the code (`foo_test.go` next to `foo.go`).
- `mkdocs build --strict` passes on every PR.
- Anti-slop conventions per
  `scaffold/.stagent/prompts/roles/developer.md`.
- New decisions go in `notes/decisions.md` with a changelog entry.
  No silent design drift.

## When stuck

Re-read `notes/decisions.md`. If your question still isn't answered:

- If it's in "Tabled" — it's out of scope; ship without it.
- If it's a genuine new question — ask the user. Don't invent.

## Local dev

```bash
go test ./...                  # unit tests
go build ./cmd/stagent         # build the main binary
go build ./cmd/fraude          # build the mock claude
mkdocs serve                   # preview docs at localhost:8000
```

CI runs `go vet`, `go test`, and `mkdocs build --strict` on every
push and PR.
MD

# ─── 6. README header pointer ─────────────────────────────────────────

# Insert a line at the top of README.md pointing at IMPLEMENTING.md.
if ! grep -q "IMPLEMENTING.md" README.md 2>/dev/null; then
  python3 - <<'PY'
import pathlib
p = pathlib.Path("README.md")
text = p.read_text()
banner = "> **Implementing this repo?** Start at [IMPLEMENTING.md](./IMPLEMENTING.md).\n\n"
# Insert after the first H1 line.
lines = text.split("\n")
for i, line in enumerate(lines):
    if line.startswith("# "):
        lines.insert(i + 1, "")
        lines.insert(i + 2, banner.rstrip())
        break
p.write_text("\n".join(lines))
PY
fi

# ─── 7. Initial commit + push ─────────────────────────────────────────

echo "→ Initializing git, committing, pushing ..."
git init -b main -q
git remote add origin "git@github.com:$GH_REPO.git"
git add .
git commit -q -m "Initial commit: docs, scaffold, decisions, Go module skeleton

Promoted from davefowler/agenttree:claude/agenttree-storage-strategy-IDtAU.
Implementation begins from the locked-in decisions in notes/decisions.md.
"
git push -u origin main

# ─── Done ────────────────────────────────────────────────────────────

cat <<DONE

✓ Done.

  Repo:  https://github.com/$GH_REPO
  Local: $TARGET_DIR
  Go:    $GO_VERSION

Next:

  cd $TARGET_DIR

  # For docs preview (optional):
  pip install mkdocs mkdocs-material pymdown-extensions
  mkdocs serve

  # Hand off to Claude Code for implementation:
  claude
  # In the session: "Read IMPLEMENTING.md and start v0.1."

DONE
