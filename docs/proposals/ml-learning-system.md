# Phase 6: ML-Based Agent Learning System

**Status:** Proposal
**Author:** AgentTree Team
**Date:** 2026-01-01
**Goal:** Enable agents to learn from past work and share knowledge across projects

## Executive Summary

This proposal outlines a machine learning-based system that allows AgentTree agents to:
1. **Learn from successful PRs** - Extract patterns and solutions from merged code
2. **Share knowledge** - Build a searchable knowledge base across projects
3. **Improve over time** - Recommend solutions based on similar past problems
4. **Transfer learning** - Apply lessons from one project to another

## Motivation

### Current State
- Agents start each task from scratch
- No memory of past solutions
- Each agent works in isolation
- Knowledge is lost after PRs are merged

### Desired State
- Agents learn from every successful PR
- Knowledge is preserved and searchable
- Agents can reference past solutions
- Cross-project learning and pattern recognition

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     AgentTree ML System                      │
└─────────────────────────────────────────────────────────────┘
                              │
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐   ┌──────────────────┐   ┌──────────────┐
│  PR Ingestion │   │ Knowledge Store  │   │   Query API  │
│               │   │                  │   │              │
│ • Extract     │──▶│ • Vector DB      │◀──│ • Semantic   │
│   commits     │   │ • Embeddings     │   │   Search     │
│ • Parse diffs │   │ • Metadata       │   │ • Similar    │
│ • Categorize  │   │ • Index          │   │   Problems   │
└───────────────┘   └──────────────────┘   └──────────────┘
        │                     │                     │
        │                     │                     │
        └─────────────────────┴─────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │   Agent Context  │
                    │                  │
                    │ • Pre-task hints │
                    │ • Code examples  │
                    │ • Pattern refs   │
                    └──────────────────┘
```

## Components

### 1. PR Ingestion Pipeline

**Purpose:** Extract learnings from successful PRs

**Workflow:**
1. Monitor merged PRs (via GitHub webhooks or polling)
2. Extract metadata:
   - Issue description
   - Commit messages
   - Code diffs
   - Files changed
   - Test results
   - Review comments
3. Categorize changes:
   - Bug fix
   - Feature addition
   - Refactoring
   - Documentation
   - Test improvement
4. Generate embeddings for semantic search

**Implementation:**
```python
class PRIngestionPipeline:
    """Extract learnings from merged PRs."""

    def ingest_pr(self, pr_number: int) -> KnowledgeEntry:
        """Process a merged PR and extract knowledge."""
        # Get PR details
        pr = get_pr_details(pr_number)

        # Extract commits and diffs
        commits = get_pr_commits(pr_number)
        diffs = get_pr_diffs(pr_number)

        # Categorize the change
        category = self._categorize_pr(pr, diffs)

        # Generate embeddings for semantic search
        embedding = self._generate_embedding(pr, commits, diffs)

        # Store in knowledge base
        return KnowledgeEntry(
            pr_number=pr_number,
            title=pr.title,
            category=category,
            commits=commits,
            diff_summary=self._summarize_diffs(diffs),
            embedding=embedding,
            metadata={
                "files_changed": [f.filename for f in diffs],
                "lines_added": sum(f.additions for f in diffs),
                "lines_deleted": sum(f.deletions for f in diffs),
                "issue_number": pr.issue_number,
            }
        )
```

### 2. Knowledge Store

**Purpose:** Persistent storage of learned knowledge with semantic search

**Technology Options:**

**Option A: Chroma (Recommended)**
- Lightweight, embedded vector database
- Python-native, easy to integrate
- Good for small-medium datasets (<1M vectors)
- No separate server needed

**Option B: Qdrant**
- High-performance vector search
- Good for larger datasets
- Supports filtering and hybrid search
- Requires separate service

**Option C: PostgreSQL + pgvector**
- Leverage existing PostgreSQL knowledge
- Good for structured + vector data
- Simpler architecture (one database)

**Recommended: Chroma** for initial implementation

**Schema:**
```python
from dataclasses import dataclass
from typing import List, Dict, Optional
import chromadb

@dataclass
class KnowledgeEntry:
    """A single piece of learned knowledge."""
    id: str  # pr-{number}-{hash}
    pr_number: int
    title: str
    category: str  # bug, feature, refactor, docs, test
    summary: str  # AI-generated summary of what was done
    diff_summary: str  # Summary of code changes
    embedding: List[float]  # Vector embedding for semantic search
    metadata: Dict  # Files, lines changed, timestamps, etc.
    project: str  # Which project this came from
    tags: List[str]  # Extracted keywords

class KnowledgeStore:
    """Manage the knowledge database."""

    def __init__(self, persist_directory: str = ".agenttree/knowledge"):
        self.client = chromadb.PersistentClient(path=persist_directory)
        self.collection = self.client.get_or_create_collection(
            name="agenttree_knowledge",
            metadata={"hnsw:space": "cosine"}
        )

    def add_entry(self, entry: KnowledgeEntry) -> None:
        """Add a knowledge entry to the store."""
        self.collection.add(
            ids=[entry.id],
            embeddings=[entry.embedding],
            documents=[entry.summary],
            metadatas=[entry.metadata]
        )

    def search_similar(
        self,
        query: str,
        query_embedding: List[float],
        n_results: int = 5,
        filters: Optional[Dict] = None
    ) -> List[KnowledgeEntry]:
        """Search for similar past solutions."""
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=filters  # e.g., {"category": "bug"}
        )
        return self._parse_results(results)
```

### 3. Embedding Generation

**Purpose:** Convert text into vector embeddings for semantic search

**Technology Options:**

**Option A: OpenAI Embeddings (text-embedding-3-small)**
- High quality
- Easy to use
- Requires API key and costs money
- 1536 dimensions

**Option B: Sentence Transformers (all-MiniLM-L6-v2)**
- Free, runs locally
- Good quality for semantic search
- 384 dimensions
- Fast inference

**Option C: Anthropic (if they release embeddings API)**
- Stay within Anthropic ecosystem
- Not yet available

**Recommended: Sentence Transformers** for cost-free local execution

**Implementation:**
```python
from sentence_transformers import SentenceTransformer

class EmbeddingGenerator:
    """Generate embeddings for semantic search."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model = SentenceTransformer(model_name)

    def generate(self, text: str) -> List[float]:
        """Generate embedding for text."""
        return self.model.encode(text).tolist()

    def generate_for_pr(self, pr: PullRequest, commits: List, diffs: List) -> List[float]:
        """Generate embedding for a PR."""
        # Combine PR title, description, commit messages
        text = f"{pr.title}\n\n{pr.body}\n\n"
        text += "\n".join([c.message for c in commits])

        # Add diff summaries
        for diff in diffs:
            text += f"\n{diff.filename}: {diff.patch}"

        # Truncate to avoid model limits
        text = text[:8000]  # Keep within reasonable limits

        return self.generate(text)
```

### 4. Query API

**Purpose:** Allow agents to search knowledge base before starting tasks

**Interface:**
```python
class KnowledgeAPI:
    """API for agents to query the knowledge base."""

    def __init__(self, store: KnowledgeStore, embedder: EmbeddingGenerator):
        self.store = store
        self.embedder = embedder

    def find_similar_solutions(
        self,
        task_description: str,
        category: Optional[str] = None,
        limit: int = 5
    ) -> List[KnowledgeEntry]:
        """Find similar past solutions for a task."""
        embedding = self.embedder.generate(task_description)

        filters = {"category": category} if category else None

        return self.store.search_similar(
            query=task_description,
            query_embedding=embedding,
            n_results=limit,
            filters=filters
        )

    def get_context_for_task(self, task_description: str) -> str:
        """Get a formatted context string to prepend to agent prompt."""
        similar = self.find_similar_solutions(task_description, limit=3)

        if not similar:
            return ""

        context = "## Past Solutions for Similar Tasks\n\n"
        for i, entry in enumerate(similar, 1):
            context += f"### {i}. {entry.title} (PR #{entry.pr_number})\n"
            context += f"{entry.summary}\n\n"
            context += f"**Files changed:** {', '.join(entry.metadata['files_changed'][:5])}\n\n"

        return context
```

### 5. Agent Integration

**Purpose:** Inject learned knowledge into agent task context

**Workflow:**
1. When creating TASK.md, search knowledge base
2. Find similar past PRs
3. Append relevant context to TASK.md
4. Agent reads enhanced task description

**Implementation:**
```python
# In agents_repo.py

def create_task_file(
    self,
    issue: Issue,
    agent_num: int,
    knowledge_api: Optional[KnowledgeAPI] = None
) -> Path:
    """Create TASK.md with optional ML-enhanced context."""

    # ... existing task creation ...

    # Add ML-learned context if available
    if knowledge_api:
        context = knowledge_api.get_context_for_task(issue.body)
        if context:
            task_content += f"\n\n{context}"

    task_file.write_text(task_content)
    return task_file
```

## Data Flow

### Learning Phase (Post-PR Merge)
```
1. PR #123 merged
        ↓
2. Webhook/polling detects merge
        ↓
3. Extract PR details, commits, diffs
        ↓
4. Generate summary with LLM (optional)
        ↓
5. Generate embedding
        ↓
6. Store in Chroma DB
        ↓
7. Knowledge available for future queries
```

### Query Phase (Pre-Task Assignment)
```
1. New issue assigned to agent
        ↓
2. Extract issue description
        ↓
3. Generate embedding for issue
        ↓
4. Query Chroma for similar past PRs
        ↓
5. Retrieve top 3-5 matches
        ↓
6. Format as context
        ↓
7. Append to TASK.md
        ↓
8. Agent reads enhanced task
```

## Privacy & Security Considerations

### Private Repositories
- All knowledge stored locally
- No external API calls for embeddings (use local Sentence Transformers)
- Knowledge DB is project-specific by default

### Cross-Project Learning
- Optional: Share knowledge across projects
- User must explicitly enable
- Useful for internal company projects

### Sensitive Data
- Filter out secrets, API keys, credentials from diffs
- Use gitignore patterns to exclude sensitive files
- Option to exclude certain PRs from learning

## Performance Considerations

### Storage
- Embeddings: ~1.5KB per entry (384 dimensions × 4 bytes)
- 1000 PRs = ~1.5MB of embeddings
- Metadata: ~5KB per entry
- Total: ~7MB per 1000 PRs

### Query Speed
- Chroma HNSW index: <100ms for 10K vectors
- Embedding generation: ~50ms (local model)
- Total query time: <200ms

### Scalability
- For <10K PRs: Chroma embedded mode (current plan)
- For 10K-100K PRs: Chroma client-server mode
- For >100K PRs: Consider Qdrant or Milvus

## Implementation Plan

### Phase 6.1: Core Infrastructure (Week 1)
- [ ] Set up Chroma DB integration
- [ ] Implement `KnowledgeStore` class
- [ ] Implement `EmbeddingGenerator` with Sentence Transformers
- [ ] Create basic PR ingestion pipeline
- [ ] Add unit tests

### Phase 6.2: PR Learning (Week 2)
- [ ] GitHub webhook for merged PRs
- [ ] Extract PR metadata, commits, diffs
- [ ] Generate embeddings
- [ ] Store in knowledge DB
- [ ] Add CLI command: `agenttree learn --pr 123`

### Phase 6.3: Query API (Week 3)
- [ ] Implement `KnowledgeAPI` class
- [ ] Semantic search functionality
- [ ] Context formatting for agents
- [ ] Add CLI command: `agenttree search "bug with API"`

### Phase 6.4: Agent Integration (Week 4)
- [ ] Modify `create_task_file()` to query knowledge
- [ ] Add knowledge context to TASK.md
- [ ] Test with real agents
- [ ] Measure impact on task completion

### Phase 6.5: Web Dashboard (Week 5)
- [ ] Add knowledge browser to web UI
- [ ] Show related PRs for current task
- [ ] Search interface
- [ ] Analytics: most referenced PRs

### Phase 6.6: Cross-Project Learning (Week 6)
- [ ] Multi-project knowledge store
- [ ] Project-specific filtering
- [ ] Knowledge export/import
- [ ] Privacy controls

## Success Metrics

### Quantitative
- **Knowledge Coverage:** % of merged PRs ingested
- **Query Speed:** <200ms average
- **Context Relevance:** Manual review of top 5 results
- **Agent Performance:** Compare task completion time before/after

### Qualitative
- Agents reference past solutions in commits
- Reduced time spent on similar tasks
- Improved code consistency across projects
- User feedback on knowledge relevance

## Future Enhancements

### Phase 7: Advanced ML Features
- **Pattern Recognition:** Identify common bug patterns
- **Code Smell Detection:** Learn from refactoring PRs
- **Test Generation Hints:** Learn test patterns
- **Documentation Improvement:** Suggest docs based on past PRs

### Phase 8: Collaborative Learning
- **Multi-Agent Discussion:** Agents query each other's knowledge
- **Confidence Scoring:** Track which suggestions were helpful
- **Feedback Loop:** Learn from agent success/failure
- **Knowledge Pruning:** Remove outdated or unhelpful entries

### Phase 9: External Knowledge
- **Stack Overflow Integration:** Search SO for similar issues
- **GitHub Public Search:** Learn from open source projects
- **Documentation Parsing:** Ingest library docs for context

## Dependencies

### Required
- `chromadb` - Vector database
- `sentence-transformers` - Embedding generation
- `torch` - Required by sentence-transformers

### Optional
- `openai` - If using OpenAI embeddings instead
- `transformers` - For custom models

## Risks & Mitigations

### Risk 1: Low Quality Embeddings
**Mitigation:** Start with Sentence Transformers, upgrade to OpenAI if needed

### Risk 2: Irrelevant Search Results
**Mitigation:** Add metadata filtering (category, files, tags), manual curation

### Risk 3: Storage Growth
**Mitigation:** Implement knowledge pruning, archive old entries

### Risk 4: Privacy Leaks
**Mitigation:** Local-only by default, secret filtering, opt-in sharing

### Risk 5: Slow Queries
**Mitigation:** HNSW indexing, caching, async queries

## Open Questions

1. **How to handle multi-file PRs?** Store as single entry or multiple?
   - **Proposed:** Single entry per PR, with file-level metadata

2. **Should we summarize PRs with LLM?** More cost but better quality
   - **Proposed:** Optional LLM summary, fallback to commit messages

3. **How to handle code evolution?** Old solutions may be outdated
   - **Proposed:** Time-decay scoring, version tagging

4. **Cross-language learning?** Python project learning from JS project
   - **Proposed:** Phase 9 enhancement, language-agnostic patterns

## Conclusion

This ML-based learning system will transform AgentTree from a stateless multi-agent framework into an **intelligent, self-improving system** that learns from every successful PR and shares knowledge across projects.

**Key Benefits:**
- ✅ Reduced time on similar tasks
- ✅ Improved code consistency
- ✅ Knowledge preservation
- ✅ Cross-project learning
- ✅ Privacy-preserving (local-first)

**Next Steps:**
1. Get feedback on this proposal
2. Approve Phase 6.1 implementation plan
3. Set up development environment with Chroma + Sentence Transformers
4. Build core infrastructure (2 weeks)
5. Test with real PRs from this project

---

**Feedback Welcome:** Please review and provide feedback on this proposal before implementation begins.
