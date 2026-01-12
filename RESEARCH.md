# Code Review Research - Issue #026

## Research Overview

This document consolidates research on AI code review best practices, tools, formats, and prompts to inform the design of AgentTree's code review stage.

## 1. AI Code Review Tools Analysis

### CodeRabbit
- **Format**: Transforms PR diffs into clear summaries with line-by-line analysis
- **Output Structure**: Actionable suggestions that can be committed with one click
- **Custom Reports**: Uses natural language prompts to generate insights with preferred format, data, and structure
- **Markdown Support**: Full markdown formatting including tables, bullet points, code blocks, headers
- **Integration**: Combines 35+ linters and static code scanners into a single workflow
- **Technology**: Uses OpenAI GPT-4.5, o3, o4-mini, and Anthropic Claude Opus 4/Sonnet 4
- **Source**: [CodeRabbit Documentation](https://docs.coderabbit.ai/guides/custom-reports)

### GitHub Copilot Code Review
- **Review Categories**: 5 main areas
  1. Security Issues (input validation, authentication, data exposure, injection vulnerabilities)
  2. Performance & Efficiency (algorithm complexity, memory usage, database optimization)
  3. Code Quality (readability, naming conventions, code duplication)
  4. Architecture & Design (design patterns, separation of concerns, error handling)
  5. Testing & Documentation (test coverage, documentation completeness)

- **Severity Levels**:
  - 🔴 Critical Issues (must fix before merge)
  - 🟡 Suggestions (improvements to consider)
  - ✅ Good Practices (what's done well)

- **Response Format**:
  1. State the problem (1 sentence)
  2. Why it matters (1 sentence, if needed)
  3. Suggested fix (snippet or specific action)

- **Customization**: Supports `copilot-instructions.md` and path-specific `*.instructions.md` files
- **Static Analysis**: Integrates CodeQL, ESLint, PMD for high-signal findings
- **Source**: [GitHub Copilot Documentation](https://docs.github.com/en/copilot/concepts/agents/code-review)

### Qodo (formerly Codium AI)
- **Focus**: Reduces review noise by highlighting only critical issues
- **Prioritization**: Separates critical issues from low-impact observations
- **Context**: Provides context-rich explanations for why issues matter
- **Automation**: Automates repetitive checks (scope validation, missing tests, standards compliance)
- **2026 Emphasis**: "Review throughput, not implementation speed, determines safe delivery velocity"
- **Workflows**: 15+ agentic workflows for IDE and PR reviews
- **Source**: [Qodo AI Tools](https://www.qodo.ai/blog/best-ai-code-review-tools-2026/)

## 2. Effective Review Formats

### Structured Instruction Format (GitHub Recommended)
```markdown
# Title and Purpose & Scope
## Naming Conventions
## Code Style
## Error Handling
## Testing
## Security
## Code Examples
## Task-Specific / Advanced Sections
  - Framework-Specific Rules
  - Advanced Tips & Edge Cases
```
**Source**: [GitHub Blog - Copilot Instructions](https://github.blog/ai-and-ml/unlocking-the-full-power-of-copilot-code-review-master-your-instructions-files/)

### Key Review Areas
From AI code review best practices research:
- Unclear logic
- Unnecessary complexity
- Code duplication
- Missing comments (where needed)
- Violations of best practices
- Missing tests
- Security flaws
- Performance bottlenecks

**Source**: [5ly.co AI Prompts for Code Review](https://5ly.co/blog/ai-prompts-for-code-review/)

### Enterprise Requirements (2026)
- System-aware reasoning
- Ticket-aligned validation
- Enforceable standards
- Automated PR workflows
- Governance for distributed teams
- Small PRs (under 400 lines ideal)

**Source**: [Qodo Blog - Best Automated Code Review Tools](https://www.qodo.ai/blog/best-automated-code-review-tools-2026/)

## 3. Example Prompts & Skills

### Simple Claude Code Review Prompt
**Focus**: Identify critical issues in:
- Potential bugs or issues
- Performance
- Security
- Correctness

**Output**:
- If critical issues found: List in bullet points
- If no critical issues: Simple approval
- Sign off with: ✅ (approved) or ❌ (issues found)

**Source**: [Jose Casanova Blog](https://www.josecasanova.com/blog/claude-code-review-prompt)

### GitHub Copilot Custom Prompt (VS Code)
**Priority Levels**:
- 🔥 Critical
- ⚠️ High
- 🟡 Medium
- 🟢 Low

**Suggestion Types**:
- 🔧 Change request
- ❓ Question
- ⛏️ Nitpick
- ♻️ Refactor suggestion

**Source**: [N+1 Blog - GitHub Copilot Prompt Engineering](https://nikiforovall.blog/productivity/2025/05/03/github-copilot-prompt-engineering-code-review.html)

### Comprehensive Code Review Gist
**Structure**: JSON object with markdown-formatted critique
**Indicators**:
- ✅ Satisfactory
- 💻 Improvement needed
- ❌ Critical issues

**Source**: [GitHub Gist - Codereview Prompt](https://gist.github.com/MehrCurry/f5f03ebb9ce0957929c95d16763debda)

### Claude Code Built-in Capabilities
- `/review-pr` command for GitHub PR reviews
- `/security-review` for comprehensive security analysis
- Detects issues beyond traditional linting: typos, stale comments, misleading names
- Code-reviewer agent example at `.claude/agents/code-reviewer.md`

**Source**: [Piebald-AI System Prompts](https://github.com/Piebald-AI/claude-code-system-prompts)

### Awesome Reviewers Repository
- Ready-to-use system prompts for agentic code review
- Each prompt distilled from thousands of real code review comments
- From leading open source repositories

**Source**: [Awesome Reviewers](https://github.com/baz-scm/awesome-reviewers)

## 4. Severity Level Standards

### Industry Standard Classification
From CVSS (Common Vulnerability Scoring System) and industry tools:

**Critical (9.0-10.0)**
- Highest level of risk, requires urgent attention
- May expose sensitive data or allow unauthorized code execution
- Blocks deployment until resolved

**High (7.0-8.9)**
- Severe risk
- May lead to accessing application resources or data exposure
- Examples: XXE, SSRF, certain XSS forms
- Addressed immediately, may block deployment

**Medium (4.0-6.9)**
- Misconfiguration or lack of security controls
- Should be addressed but not blocking

**Low (0.1-3.9)**
- Minor issues, informational

**Source**: [Snyk Severity Levels](https://docs.snyk.io/manage-risk/prioritize-issues-for-fixing/severity-levels)

## 5. Self-Review Best Practices

### Before Submitting PR
1. **Always perform self-review first** - Read through code changes carefully
2. **Take a break** - Step away and return with fresh eyes
3. **Keep PRs small** - Small, incremental, coherent changes (under 400 lines ideal)
4. **Run tests** - Ensure code actually works
5. **Provide clear descriptions** - Use PR templates
6. **Use automated tools** - Run static code analysis

**Source**: [Medium - Perfect PR Review Checklist](https://medium.com/@dorinbaba/the-perfect-pr-review-checklist-no-one-is-talking-about-50ca213a4ac1)

### Self-Review Checklist Items
- **Readability**: Simple to read? Descriptive names?
- **Code standards**: Principles and project standards respected?
- **Naming conventions**: Variables, classes, messages appropriately named?
- **Personal checklist**: Common mistakes you tend to make?
- **Diff inspection**: Scrutinize every line changed

**Source**: [Eleo Pard Solutions - Best Practices for Code Reviews](https://eleopardsolutions.com/best-practices-for-code-reviews-self-review-vs-peer-review/)

## 6. Review Categories & Structure

### Five Main Focus Areas
From comprehensive code quality research:

1. **Security**
   - SAST scanning for common vulnerabilities
   - OWASP Top 10, CWE Top 25 compliance
   - Known CVEs, malicious patterns
   - Input validation, authentication

2. **Performance**
   - Algorithm complexity
   - Memory usage
   - Database query optimization
   - Code efficiency

3. **Maintainability**
   - Readability (clear code)
   - Updates/fixes don't break features
   - Code structure and organization
   - Code duplication

4. **Testing**
   - Code coverage insights
   - Untested lines highlighted
   - Test quality and completeness

5. **Architecture**
   - Design patterns
   - Separation of concerns
   - Error handling
   - Code structure

**Source**: [CodeAnt Complete Code Review Process](https://www.codeant.ai/blogs/good-code-review-practices-guide)

## 7. Key Insights for AgentTree Implementation

### What Makes Reviews Effective
1. **Separation of concerns**: Critical vs suggestions vs notes
2. **Actionable feedback**: Specific, not vague
3. **Context-aware**: Explains why issues matter
4. **Prioritized**: Clear severity levels
5. **Structured output**: Consistent format using markdown
6. **Automated validation**: Tools check before human review
7. **Self-reflection**: Agent must review its own work first

### Template Requirements
Based on research, our `review.md` should include:

1. **Header**: Issue number and context
2. **Critical Issues Section**: MUST be empty before PR (blocking)
3. **High Priority Section**: Should be addressed before PR
4. **Suggestions Section**: Non-blocking improvements
5. **Good Practices Section**: What's done well (positive reinforcement)
6. **Notes Section**: Context for reviewer
7. **Self-Review Checklist**: Verification steps completed

### Prompt Engineering for /review Skill
Key elements from research:
- Clear, explicit instructions (Claude 4 best practice)
- Focus on 5 main categories (Security, Performance, Maintainability, Testing, Architecture)
- Use severity levels (Critical, High, Medium, Low)
- Provide structured markdown output
- Include context and "why it matters"
- Be specific and actionable
- Look beyond linting: typos, stale comments, misleading names

## 8. Recommended Implementation

### review.md Template Structure
```markdown
# Code Review - Issue #XXX

## Critical Issues (Blocking)
<!-- MUST be empty before creating PR -->
<!-- Issues that must be fixed: security vulnerabilities, major bugs, data loss risks -->

## High Priority Issues
<!-- Should be addressed before PR: significant bugs, performance issues, broken functionality -->

## Suggestions
<!-- Optional improvements, not blocking -->
<!-- Format: - Category: Description with context -->

## Good Practices
<!-- Positive feedback on what's done well -->

## Notes for Reviewer
<!-- Any context, tradeoffs, or areas needing human judgment -->

## Self-Review Checklist
- [ ] All tests pass
- [ ] Code follows project standards
- [ ] No security vulnerabilities
- [ ] Performance is acceptable
- [ ] Documentation updated
- [ ] No TODO/FIXME comments left unresolved
- [ ] Diff reviewed line-by-line
```

### /review Skill Characteristics
- Systematic analysis across 5 categories
- Clear severity classification
- Actionable, specific feedback
- Context explanations
- Markdown-formatted output
- Integration with review.md template
- Pre-PR validation hook

## 9. Sources

### AI Code Review Tools
- [CodeRabbit Documentation](https://docs.coderabbit.ai/guides/custom-reports)
- [GitHub Copilot Code Review Docs](https://docs.github.com/en/copilot/concepts/agents/code-review)
- [Qodo AI Code Review Tools 2026](https://www.qodo.ai/blog/best-ai-code-review-tools-2026/)

### Prompt Examples
- [Jose Casanova - Simple Claude Code Review Prompt](https://www.josecasanova.com/blog/claude-code-review-prompt)
- [GitHub Blog - Unlocking Copilot Code Review](https://github.blog/ai-and-ml/unlocking-the-full-power-of-copilot-code-review-master-your-instructions-files/)
- [Piebald-AI Claude Code System Prompts](https://github.com/Piebald-AI/claude-code-system-prompts)
- [Awesome Reviewers Repository](https://github.com/baz-scm/awesome-reviewers)

### Best Practices
- [5ly.co - AI Prompts for Code Review](https://5ly.co/blog/ai-prompts-for-code-review/)
- [CodeAnt - Complete Code Review Process](https://www.codeant.ai/blogs/good-code-review-practices-guide)
- [Medium - Perfect PR Review Checklist](https://medium.com/@dorinbaba/the-perfect-pr-review-checklist-no-one-is-talking-about-50ca213a4ac1)
- [Eleo Pard Solutions - Self vs Peer Review](https://eleopardsolutions.com/best-practices-for-code-reviews-self-review-vs-peer-review/)

### Standards
- [Snyk Severity Levels](https://docs.snyk.io/manage-risk/prioritize-issues-for-fixing/severity-levels)
- [Sherlock - Understanding Vulnerabilities](https://sherlock.xyz/post/understanding-critical-high-medium-and-low-vulnerabilities-in-smart-contracts)

### Additional Resources
- [mgreiler/code-review-checklist](https://github.com/mgreiler/code-review-checklist)
- [awesome-claude-skills](https://github.com/travisvn/awesome-claude-skills)
- [Microsoft Engineering Playbook - Markdown Code Reviews](https://microsoft.github.io/code-with-engineering-playbook/code-reviews/recipes/markdown/)
