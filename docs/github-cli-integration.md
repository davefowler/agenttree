# GitHub CLI Integration Research

## Current Capabilities

### Creating Repositories with `gh` CLI

Yes! The `gh` CLI can create repositories:

```bash
# Create a new repo
gh repo create myproject-agents --private --description "AI agent notes"

# Clone it immediately
gh repo create myproject-agents --private --clone

# Create without cloning
gh repo create myproject-agents --private --gitignore Python

# Check if user is authenticated
gh auth status
```

### Authentication Check

```bash
# Check if logged in
gh auth status
# Output if logged in:
#   github.com
#     ✓ Logged in to github.com as username (keyring)
#     ✓ Git operations for github.com configured to use https protocol.
#     ✓ Token: *******************

# Output if NOT logged in:
#   You are not logged into any GitHub hosts. Run gh auth login to authenticate.

# Login flow
gh auth login
# Interactive prompts:
# - What account? GitHub.com
# - Protocol? HTTPS
# - Authenticate? Login with browser
# - Opens browser for OAuth
```

## Security Considerations

### Option 1: Use `gh` CLI (Current Approach)

**Pros:**
- ✅ User controls their own auth
- ✅ Uses user's existing GitHub permissions
- ✅ No need to store tokens in AgentTree
- ✅ Leverages GitHub's OAuth flow
- ✅ User can revoke access anytime via GitHub settings

**Cons:**
- ❌ Requires `gh` CLI installed
- ❌ Full GitHub access (can't restrict)
- ❌ If agent compromised, has full user permissions

**Risk:** If running in `--dangerous` mode (no permissions), agent could:
- Create repos
- Delete repos
- Push to any repo user has access to

### Option 2: GitHub API with Fine-Grained Token

**Pros:**
- ✅ Can restrict to specific permissions (repos only)
- ✅ Can restrict to specific repositories
- ✅ Token can be revoked independently
- ✅ More secure for autonomous agents

**Cons:**
- ❌ User has to manually create token
- ❌ Have to store token somewhere (config file, env var)
- ❌ More setup friction

**Token creation:**
```bash
# User creates fine-grained token with:
# - Repository permissions: Contents (read/write), Metadata (read)
# - Only for organization/repositories they choose

# Store in .agenttree.yaml
github:
  token: ghp_xxxxxxxxxxxx  # Fine-grained PAT
```

### Option 3: Hybrid Approach (Recommended)

Use `gh` CLI but **wrap all GitHub operations** in AgentTree functions:

```python
# agenttree/github_client.py
class GitHubClient:
    """Controlled interface to GitHub."""

    ALLOWED_OPERATIONS = [
        "repo.create",      # Can create repos
        "issue.read",       # Can read issues
        "issue.edit",       # Can add labels
        "pr.create",        # Can create PRs
        "pr.checks",        # Can read CI status
    ]

    def create_repo(self, name: str, private: bool = True):
        """Create a repository (controlled)."""
        # Validate name
        if not name.endswith("-agents"):
            raise ValueError("Agent repos must end with '-agents'")

        # Ask user for confirmation in non-dangerous mode
        if not self.dangerous_mode:
            click.confirm(f"Create GitHub repo '{name}'?", abort=True)

        # Execute
        subprocess.run(["gh", "repo", "create", name, "--private"])

    def delete_repo(self, name: str):
        """BLOCKED: Cannot delete repos."""
        raise PermissionError(
            "AgentTree cannot delete repositories for safety. "
            "Delete manually via GitHub web interface."
        )
```

**Benefits:**
- ✅ Simpler setup (use existing `gh` auth)
- ✅ Limited operations (can't delete, can't push to main repo)
- ✅ Confirmation prompts for sensitive operations
- ✅ Can audit what agents are allowed to do

## Recommendation

**Use `gh` CLI with wrapped operations:**

1. Check if `gh` is installed and authenticated
2. Wrap all GitHub operations in `GitHubClient` class
3. Whitelist only safe operations
4. Add confirmation prompts for repo creation
5. Block dangerous operations (delete, force push)

**Error messages:**

```python
def ensure_gh_authenticated():
    """Check if gh CLI is authenticated."""
    if not shutil.which("gh"):
        raise RuntimeError(
            "GitHub CLI (gh) not found.\n\n"
            "Install: https://cli.github.com/\n"
            "  macOS:   brew install gh\n"
            "  Linux:   (see website)\n"
            "  Windows: (see website)\n"
        )

    result = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Not authenticated with GitHub.\n\n"
            "Run: gh auth login\n\n"
            "This will open your browser to authenticate.\n"
            "AgentTree uses your GitHub credentials to:\n"
            "  - Create agent notes repositories\n"
            "  - Fetch issues\n"
            "  - Create pull requests\n"
            "  - Monitor CI status\n"
        )
```

## Future: Fine-Grained Tokens (Optional)

Add support for fine-grained tokens as an alternative:

```yaml
# .agenttree.yaml
github:
  auth_method: gh_cli        # or 'token'
  token: null                # Only if auth_method: token

  # Permissions AgentTree needs:
  # - repo:contents:read,write (for agents repo)
  # - repo:issues:read (for task dispatch)
  # - repo:pull_requests:write (for creating PRs)
```

This gives advanced users more control while keeping simple setup for most users.
