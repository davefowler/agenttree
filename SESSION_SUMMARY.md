# Session Summary - 2026-01-11

**Branch:** `claude/implement-spec-tdd-AoiCs`
**Status:** All changes committed and pushed ✅

---

## What Was Built

### 1. **Comprehensive Kanban Workflow Plan**
**File:** `PLAN_KANBAN_WORKFLOW.md` (872 lines)

Major architectural shift from GitHub-centric to custom kanban workflow:

**Key Decisions:**
- ✅ Separate `agents/` repository as source of truth (not GitHub Issues)
- ✅ 9 kanban stages: Backlog → Problem → Problem Review → Research/Plan → Plan Review → Implement → Implementation Review → Accepted → Not Doing
- ✅ **One agent per task** (no task switching - major simplification)
- ✅ Local CI enforcement (quick_ci.sh, ci.sh, extensive_ci.sh)
- ✅ Claude Review API instead of GitHub PR reviews
- ✅ Stage-specific skills/instructions for agents
- ✅ Helper scripts for all operations (pull → edit → push pattern)

**Architecture:**
```
agents/                      # Separate git repo
├── issues/                  # One dir per issue
│   ├── 001-login-bug/
│   │   ├── issue.yaml       # Metadata (stage, agent, dates)
│   │   ├── problem.md       # Problem statement (stage 1)
│   │   ├── plan.md          # Implementation plan (stage 3)
│   │   ├── review.md        # Code review notes (stage 6)
│   │   └── commit-log.md    # What was done
│   └── archive/             # Completed issues
├── templates/               # Templates for each stage
├── scripts/                 # Helper scripts
│   ├── new-issue.sh
│   ├── edit-issue.sh
│   ├── move-stage.sh
│   └── review-issue.sh
└── skills/                  # Stage-specific agent skills
    ├── 1-problem/
    ├── 3-research/
    ├── 5-implement/
    └── 6-review/
```

**Implementation Phases:**
1. Repository structure and helper scripts
2. Kanban web UI with HTMX
3. CI scripts with templates
4. Claude review integration
5. One agent per task refactor

---

### 2. **Dual View Web UI: Kanban + Flow**

**Both views implemented with shared detail template!**

#### **Kanban View** (`/kanban`)
- Column-based board with 9 stages
- Drag-and-drop cards between columns
- Click card → modal opens with full details
- **Minimal JS:** ~60 lines total (just drag-drop)
- POST to `/api/issues/{id}/move` on drop
- HTMX loads detail in modal

#### **Flow View** (`/flow`)
- Inbox-style: sidebar + focus panel
- Left: Issue list sorted by priority
- Right: Full detail view
- Click issue → loads detail via HTMX
- Auto-refresh every 10 seconds

#### **Shared Components**

**Detail Template** (`partials/issue_detail.html`):
- Used by BOTH kanban modal and flow panel
- Shows: title, stage, body, labels, assignees, timestamps
- Actions: View on GitHub, Dispatch to Agent

**Pydantic Models** (`web/models.py`):
```python
StageEnum        # 9 kanban stages
Issue           # Full issue model with validation
IssueUpdate     # Update requests
IssueMoveRequest # Stage transitions
KanbanBoard     # Board state
```

**Backend Endpoints:**
```python
GET  /kanban                      # Board view
GET  /flow                        # Inbox view
GET  /api/issues/{id}/detail      # Shared detail (HTMX)
POST /api/issues/{id}/move        # Stage change (drag-drop)
GET  /flow/issues                 # Issue list refresh
```

**Navigation Tabs:**
```
Dashboard | Kanban | Flow
```

---

## Architecture Highlights

### **JS-Light Design**
- Total JavaScript: ~60 lines
- Only for: drag-drop, modal open/close, escape key
- Everything else: HTMX + backend rendering
- Backend handles all state with Pydantic models

### **FastAPI Best Practices**
- Proper Pydantic models for all data
- Type-safe request/response models
- Validation at API boundaries
- Clear separation of concerns

### **Template Reuse**
- `issue_detail.html` shared by both views
- Reduces duplication
- Single source of truth for detail rendering
- Easy to maintain and extend

---

## Current State

### **What Works Now:**
✅ Kanban board with drag-drop
✅ Flow inbox with focused view
✅ Shared detail template
✅ Tab navigation
✅ HTMX-driven updates
✅ Pydantic models
✅ GitHub issue integration

### **What's Still Needed:**

#### **Phase 1: agents/ Repository Setup**
- [ ] Create agents/ git repository structure
- [ ] Implement helper scripts (new-issue.sh, move-stage.sh, edit-issue.sh)
- [ ] Write stage templates (problem.md, plan.md, review.md)
- [ ] Create stage-specific skills

#### **Phase 2: Backend Integration**
- [ ] Replace GitHub API with agents/ repo reading
- [ ] Implement `/api/issues/{id}/move` to update issue.yaml
- [ ] Add pull → update → commit → push logic
- [ ] Load issues from `agents/issues/*/issue.yaml` files

#### **Phase 3: CI Scripts**
- [ ] Create quick_ci.sh template
- [ ] Create ci.sh template
- [ ] Create extensive_ci.sh template
- [ ] Add CI enforcement on stage transitions

#### **Phase 4: Claude Review Integration**
- [ ] Create review-issue.sh script
- [ ] Integrate Claude API for code review
- [ ] Add review button in implementation_review stage
- [ ] Save reviews to review.md

#### **Phase 5: One Agent Per Task**
- [ ] Remove task switching logic
- [ ] Update dispatch to assign one agent per issue
- [ ] Free agent when issue moves to "Accepted"
- [ ] Update agent status to reflect issue stage

---

## Files Changed This Session

### **New Files:**
1. `PLAN_KANBAN_WORKFLOW.md` - Comprehensive architecture plan
2. `agenttree/web/models.py` - Pydantic models
3. `agenttree/web/templates/kanban.html` - Kanban board UI
4. `agenttree/web/templates/partials/issue_detail.html` - Shared detail template

### **Modified Files:**
1. `agenttree/github.py` - Added list_issues(), sort_issues_by_priority()
2. `agenttree/web/app.py` - Added kanban endpoints, updated flow
3. `agenttree/web/templates/dashboard.html` - Added navigation tabs
4. `agenttree/web/templates/flow.html` - Updated to use shared template
5. `agenttree/web/templates/partials/flow_issues_list.html` - Use shared endpoint

### **Removed Files:**
1. `agenttree/web/templates/partials/flow_issue_detail.html` - Replaced with shared template

---

## Key Technical Details

### **Stage Mapping**
Currently maps GitHub labels to stages:
```python
# Label format: "stage-backlog", "stage-problem", etc.
for label in issue.labels:
    if label.startswith("stage-"):
        stage_name = label.replace("stage-", "").replace("-", "_")
        stage = StageEnum(stage_name)
```

**TODO:** Replace with `agents/issues/*/issue.yaml` reading:
```yaml
number: 42
stage: implement
assigned_agent: 1
```

### **Drag-Drop Implementation**
Pure vanilla JS, no libraries:
```javascript
// ~30 lines for drag-drop
document.addEventListener('dragstart', ...);
document.addEventListener('drop', async (e) => {
    // POST to /api/issues/{id}/move
    await fetch(`/api/issues/${issueNumber}/move`, {
        method: 'POST',
        body: JSON.stringify({stage: newStage})
    });
});
```

### **HTMX Patterns**
```html
<!-- Auto-refresh every 10s -->
<div hx-get="/flow/issues"
     hx-trigger="load, every 10s"
     hx-swap="innerHTML">
</div>

<!-- Load on click -->
<div hx-get="/api/issues/42/detail"
     hx-target="#issue-detail"
     hx-swap="innerHTML">
</div>
```

---

## Testing The UI

### **Start the server:**
```bash
agenttree web
# or
python -m agenttree.web.app
```

### **Visit:**
- http://localhost:8080/ - Dashboard (agent status)
- http://localhost:8080/kanban - Kanban board
- http://localhost:8080/flow - Flow inbox

### **Test drag-drop:**
1. Open kanban view
2. Drag a card to different column
3. Check browser console for POST request
4. Currently returns mock success (TODO: implement real update)

---

## Important Context for Next Session

### **The Big Picture:**
We're building a TDD workflow where:
1. Each issue goes through well-defined stages
2. One agent works on one issue exclusively
3. Stage transitions have specific requirements (CI, reviews, etc.)
4. All state is tracked in `agents/` repo
5. Web UI provides both overview (kanban) and focused (flow) views

### **Priority Next Steps:**
1. **Create agents/ repo structure** - Foundation for everything
2. **Implement helper scripts** - new-issue.sh, move-stage.sh
3. **Connect backend to agents/ repo** - Stop using GitHub API
4. **CI script templates** - quick_ci.sh, ci.sh, extensive_ci.sh

### **User Preferences:**
- ✅ JS-light (minimal JavaScript)
- ✅ FastAPI + Pydantic best practices
- ✅ HTMX for interactivity
- ✅ Backend handles all state
- ✅ Both kanban and flow views (serve different purposes)

---

## Git Status

**Branch:** `claude/implement-spec-tdd-AoiCs`
**Status:** Clean - all changes committed and pushed ✅

**Recent Commits:**
```
8620c54 Add Kanban view alongside Flow view with shared detail template
f893d84 Add comprehensive plan for kanban workflow with agents/ repo
e04da64 Add Flow tab to web UI with inbox-style task management
672b11e Implement Phases 2-3: CLI tools and task re-engagement
c20b383 Implement Phase 1: Frontmatter and context summary pre-creation
```

---

## Questions to Address Next Session

1. **Do we want sub-stages visible in UI?** (e.g., "5c: Implementing" vs just "Implement")
2. **Should we create a new branch for agents/ repo work?** Or continue on same branch?
3. **CI script defaults** - What should quick_ci.sh check? (ruff, mypy, etc.)
4. **Stage skill format** - Markdown files with instructions? Or something else?

---

## Notes

- Session expired before we could continue
- All work is saved and pushed
- Ready to pick up from here
- UI is functional but needs backend connection to agents/ repo
- Plan document is comprehensive and ready for implementation

**Next agent should read:**
1. This summary
2. PLAN_KANBAN_WORKFLOW.md
3. Check out the kanban and flow UIs in browser
