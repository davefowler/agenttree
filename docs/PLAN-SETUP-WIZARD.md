# Plan: AgentTree Setup Wizard & Onboarding

**Goal**: Make it trivially easy for users to set up their first worktree and start using AgentTree in under 2 minutes.

**Problem**: Currently users need to:
1. Understand git worktrees (many developers have never used them)
2. Copy bash scripts manually
3. Configure project-specific setup (venv, dependencies, env vars)
4. Understand tmux
5. Know which AI tool to use

This is a 15+ minute setup with multiple failure points.

---

## User Experience Target

```bash
# Fresh repo - zero setup
cd ~/Projects/myapp
agenttree init

# Interactive wizard:
# ✓ Detected Python project (pyproject.toml found)
# ✓ Detected .env file
#
# How many agents? [3]: 3
# Default AI tool? (claude/aider/custom) [claude]: claude
# Where to store worktrees? [~/Projects/worktrees]: <enter>
#
# Setting up 3 agents...
# ✓ Agent 1 ready at ~/Projects/worktrees/myapp-agent-1
# ✓ Agent 2 ready at ~/Projects/worktrees/myapp-agent-2
# ✓ Agent 3 ready at ~/Projects/worktrees/myapp-agent-3
#
# 🎉 Ready! Try: agenttree dispatch 1 --task "Fix the login bug"

# First dispatch - auto-configures
agenttree dispatch 1 --task "Add user settings page"

# Wizard detects missing config and helps:
# ⚠️  First dispatch! Let me help configure your project.
#
# How should I setup the environment?
# 1. Python (venv + pip install)
# 2. Node.js (npm install)
# 3. Custom command
# Choice [1]: 1
#
# Requirements file? [requirements.txt]: pyproject.toml
# Python version? [3.11]: <enter>
# Additional setup needed? (e.g., database) [none]: docker compose up -d postgres
#
# Saving to .agenttree/setup.sh...
# ✓ Environment ready
# ✓ Agent started in tmux: myapp-agent-1
```

**Time to first agent working: < 2 minutes**

---

## Implementation Plan

### Phase 1: Smart Detection (Week 1)

Create project type detection system:

```python
# agenttree/detection.py

class ProjectDetector:
    """Auto-detect project type and requirements"""

    def detect(self, path: Path) -> ProjectConfig:
        """Detect project configuration"""
        config = ProjectConfig()

        # Language/framework detection
        if (path / "pyproject.toml").exists():
            config.type = "python"
            config.install_cmd = "pip install -e '.[dev]'"
            config.venv = True

        elif (path / "package.json").exists():
            config.type = "node"
            pkg = json.loads((path / "package.json").read_text())
            config.install_cmd = "npm install"

        elif (path / "Cargo.toml").exists():
            config.type = "rust"
            config.install_cmd = "cargo build"

        elif (path / "go.mod").exists():
            config.type = "go"
            config.install_cmd = "go mod download"

        # Environment detection
        if (path / ".env").exists():
            config.has_env = True
            config.env_template = path / ".env"

        if (path / ".env.example").exists():
            config.env_template = path / ".env.example"

        # Docker detection
        if (path / "docker-compose.yml").exists():
            config.has_docker = True
            config.docker_services = self._parse_compose(path)

        # Database detection
        config.databases = self._detect_databases(path)

        return config

    def _detect_databases(self, path: Path) -> list[str]:
        """Check for database configuration"""
        dbs = []

        # Check .env for database URLs
        env_file = path / ".env"
        if env_file.exists():
            content = env_file.read_text()
            if "postgres" in content.lower():
                dbs.append("postgres")
            if "mysql" in content.lower():
                dbs.append("mysql")
            if "redis" in content.lower():
                dbs.append("redis")

        return dbs
```

**Detection features:**
- ✅ Auto-detect Python/Node/Rust/Go
- ✅ Find package managers (pip, npm, cargo, etc.)
- ✅ Detect environment files
- ✅ Detect Docker Compose services
- ✅ Detect database requirements
- ✅ Parse existing CI config for hints

### Phase 2: Interactive Setup Wizard (Week 1-2)

```python
# agenttree/wizard.py

class SetupWizard:
    """Interactive project setup"""

    def run_init(self, repo_path: Path):
        """Initialize AgentTree in a repository"""

        print("🌲 AgentTree Setup\n")

        # Detect project
        detector = ProjectDetector()
        detected = detector.detect(repo_path)

        print(f"✓ Detected {detected.type} project")
        if detected.has_docker:
            print(f"✓ Found Docker Compose ({', '.join(detected.docker_services)})")
        if detected.databases:
            print(f"✓ Found databases: {', '.join(detected.databases)}")
        print()

        # Ask questions with smart defaults
        config = {}
        config['num_agents'] = self._ask_int(
            "How many agents?",
            default=3,
            range=(1, 10)
        )

        config['ai_tool'] = self._ask_choice(
            "Default AI tool?",
            choices=["claude", "aider", "custom"],
            default="claude"
        )

        config['worktrees_dir'] = self._ask_path(
            "Where to store worktrees?",
            default=Path.home() / "Projects/worktrees"
        )

        # Project-specific setup
        if detected.type == "python":
            config['python_version'] = self._ask_str(
                "Python version?",
                default=self._detect_python_version()
            )

            if detected.venv:
                config['venv_type'] = self._ask_choice(
                    "Virtual environment?",
                    choices=["venv", "virtualenv", "uv"],
                    default="venv"
                )

        # Environment setup
        if detected.has_env:
            use_env = self._ask_bool(
                "Copy .env to each agent?",
                default=True
            )
            if use_env:
                config['copy_env'] = True
                config['env_template'] = detected.env_template

        # Docker services
        if detected.docker_services:
            services = self._ask_multiselect(
                "Which Docker services should agents start?",
                choices=detected.docker_services,
                default=detected.docker_services
            )
            config['docker_services'] = services

        # Port allocation
        if self._needs_ports(detected):
            base_port = self._ask_int(
                "Base port for agents? (each gets port+N)",
                default=8001
            )
            config['port_base'] = base_port

        # Additional setup
        custom_setup = self._ask_str(
            "Additional setup command? (optional)",
            default="",
            optional=True
        )
        if custom_setup:
            config['custom_setup'] = custom_setup

        # Generate setup script
        self._generate_setup_script(repo_path, config, detected)

        # Generate config file
        self._write_config(repo_path / ".agenttree/config.yaml", config)

        # Create agents
        print(f"\nSetting up {config['num_agents']} agents...")
        for i in range(1, config['num_agents'] + 1):
            self._setup_agent(i, config, detected)
            print(f"✓ Agent {i} ready")

        # Success message
        print(f"\n🎉 AgentTree initialized!")
        print(f"\nNext steps:")
        print(f"  agenttree dispatch 1 --task \"Your first task\"")
        print(f"  agenttree status")
        print(f"  agenttree attach 1")

    def _generate_setup_script(self, repo_path: Path, config: dict, detected: ProjectConfig):
        """Generate custom setup script for this project"""

        script_path = repo_path / ".agenttree/setup.sh"
        script_path.parent.mkdir(exist_ok=True)

        script = ["#!/bin/bash", "set -e", ""]

        # Add project-specific setup
        if detected.type == "python":
            script.extend([
                "# Python setup",
                f"python{config.get('python_version', '3.11')} -m venv .venv",
                "source .venv/bin/activate",
                "pip install --quiet --upgrade pip",
                f"pip install --quiet {detected.install_cmd}",
                ""
            ])

        elif detected.type == "node":
            script.extend([
                "# Node.js setup",
                f"{detected.install_cmd}",
                ""
            ])

        # Docker setup
        if config.get('docker_services'):
            services = ' '.join(config['docker_services'])
            script.extend([
                "# Docker services",
                f"docker compose up -d {services}",
                ""
            ])

        # Environment setup
        if config.get('copy_env'):
            script.extend([
                "# Environment",
                f"cp {config['env_template']} .env",
                ""
            ])

        # Port configuration
        if 'port_base' in config:
            script.extend([
                "# Port configuration",
                "AGENT_NUM=$1",
                "PORT=$((PORT_BASE + AGENT_NUM))",
                'sed -i.bak "s/^PORT=.*/PORT=$PORT/" .env',
                ""
            ])

        # Custom setup
        if config.get('custom_setup'):
            script.extend([
                "# Custom setup",
                config['custom_setup'],
                ""
            ])

        script_path.write_text('\n'.join(script))
        script_path.chmod(0o755)
```

**Wizard features:**
- ✅ Smart defaults based on detection
- ✅ Skip obvious questions (don't ask about Python version if pyproject.toml has it)
- ✅ Visual progress indicators
- ✅ Generates project-specific setup.sh
- ✅ Creates .agenttree/config.yaml
- ✅ Sets up all agents in one go

### Phase 3: Template Library (Week 2)

Common project templates users can bootstrap from:

```python
# agenttree/templates.py

TEMPLATES = {
    "django": {
        "name": "Django Project",
        "files": {
            ".agenttree/setup.sh": """
#!/bin/bash
set -e
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
            """,
            "AGENTS.md": """
# Agent Instructions

## Setup
This Django project uses PostgreSQL. Each agent has its own database.

## Workflow
1. Read TASK.md
2. Create branch: `git checkout -b issue-X`
3. Make changes
4. Run tests: `python manage.py test`
5. Submit: `./scripts/submit.sh`
            """
        },
        "config": {
            "port_base": 8000,
            "docker_services": ["postgres"]
        }
    },

    "nextjs": {
        "name": "Next.js Project",
        "files": {
            ".agenttree/setup.sh": """
#!/bin/bash
set -e
npm install
npm run build
            """
        },
        "config": {
            "port_base": 3000
        }
    },

    "fastapi": {
        "name": "FastAPI Project",
        "files": {
            ".agenttree/setup.sh": """
#!/bin/bash
set -e
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
            """
        },
        "config": {
            "port_base": 8000
        }
    }
}

class TemplateManager:
    """Manage project templates"""

    def list_templates(self) -> dict:
        """List available templates"""
        return TEMPLATES

    def apply_template(self, repo_path: Path, template_name: str):
        """Apply a template to initialize the project"""
        template = TEMPLATES[template_name]

        # Create files
        for file_path, content in template['files'].items():
            full_path = repo_path / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content.strip())

        # Merge config
        return template['config']
```

**Usage:**
```bash
agenttree init --template django
agenttree init --template nextjs
agenttree init --template fastapi
```

### Phase 4: Validation & Health Checks (Week 2)

```python
# agenttree/validation.py

class SetupValidator:
    """Validate setup before first use"""

    def validate_agent(self, agent_num: int) -> ValidationResult:
        """Check if an agent is properly configured"""

        result = ValidationResult()
        worktree = self.get_worktree(agent_num)

        # Check worktree exists
        if not worktree.exists():
            result.error("Worktree doesn't exist")
            return result

        # Check dependencies installed
        if (worktree / "pyproject.toml").exists():
            if not (worktree / ".venv").exists():
                result.warning("No virtual environment found")
                result.suggest("Run setup script")
            else:
                # Check if dependencies are installed
                try:
                    # Try importing the package
                    result.check_python_imports(worktree)
                except ImportError as e:
                    result.warning(f"Missing dependencies: {e}")

        # Check environment
        if not (worktree / ".env").exists():
            result.warning("No .env file")

        # Check Docker services
        required_services = self.config.get('docker_services', [])
        running_services = self._check_docker_services()
        missing = set(required_services) - set(running_services)
        if missing:
            result.warning(f"Docker services not running: {', '.join(missing)}")
            result.suggest(f"docker compose up -d {' '.join(missing)}")

        # Check AI tool available
        ai_tool = self.config.get('ai_tool', 'claude')
        if not shutil.which(ai_tool):
            result.error(f"AI tool '{ai_tool}' not found in PATH")
            result.suggest(f"Install {ai_tool}")

        return result

# Run validation before dispatch
def dispatch_with_validation(agent_num: int, task: str):
    validator = SetupValidator()
    result = validator.validate_agent(agent_num)

    if result.has_errors():
        print("❌ Agent not ready:")
        for error in result.errors:
            print(f"  • {error}")
        print("\nFix these issues before dispatching.")
        sys.exit(1)

    if result.has_warnings():
        print("⚠️  Warnings:")
        for warning in result.warnings:
            print(f"  • {warning}")

        if result.suggestions:
            print("\nSuggested fixes:")
            for suggestion in result.suggestions:
                print(f"  $ {suggestion}")

        if not click.confirm("\nContinue anyway?"):
            sys.exit(0)

    # All good - dispatch
    do_dispatch(agent_num, task)
```

### Phase 5: First-Run Experience (Week 3)

Optimize the very first dispatch:

```python
# agenttree/first_run.py

def first_dispatch_flow(agent_num: int, task: str):
    """Handle first dispatch with extra guidance"""

    # Check if this is truly the first dispatch
    state_file = Path(".agenttree/state.json")
    if state_file.exists():
        state = json.loads(state_file.read_text())
        if state.get('first_dispatch_complete'):
            # Not first time - normal dispatch
            return normal_dispatch(agent_num, task)

    print("🎉 This is your first dispatch! Let me guide you.\n")

    # Show what's about to happen
    print("Here's what will happen:")
    print(f"1. Create/reset worktree for agent-{agent_num}")
    print(f"2. Run setup script (.agenttree/setup.sh)")
    print(f"3. Create TASK.md with your task")
    print(f"4. Start {config.ai_tool} in tmux session")
    print(f"5. Send initial prompt to agent")
    print()

    # Offer to watch
    watch = click.confirm("Would you like to watch the agent work? (recommended)", default=True)

    # Do the dispatch
    do_dispatch(agent_num, task, interactive=watch)

    if watch:
        print("\n📺 Attaching to agent session...")
        print("   (Press Ctrl+B, then D to detach)\n")
        time.sleep(2)
        attach_to_agent(agent_num)
    else:
        print(f"\n✓ Agent started in background")
        print(f"\nTo watch progress:")
        print(f"  agenttree attach {agent_num}")
        print(f"\nTo check status:")
        print(f"  agenttree status")

    # Mark first dispatch complete
    state = state if state_file.exists() else {}
    state['first_dispatch_complete'] = True
    state_file.parent.mkdir(exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2))
```

### Phase 6: Troubleshooting Guide (Week 3)

Built-in diagnostics:

```bash
# If something breaks, run:
agenttree doctor

# Output:
# AgentTree Health Check
#
# ✓ Git worktrees supported
# ✓ tmux installed (v3.3a)
# ✓ gh CLI installed (v2.40.1)
# ✓ Python 3.11 found
# ✓ Docker running
# ✗ claude not found in PATH
#
# Agent 1:
#   ✓ Worktree exists
#   ✓ Virtual environment
#   ✗ Missing dependency: pytest
#   ⚠  No .env file
#
# Suggested fixes:
#   $ npm install -g @anthropic-ai/claude-code
#   $ cd ~/Projects/worktrees/myapp-agent-1 && source .venv/bin/activate && pip install pytest
#   $ cp .env.example ~/Projects/worktrees/myapp-agent-1/.env
```

---

## Implementation Timeline

| Week | Deliverable | Features |
|------|-------------|----------|
| 1 | Detection System | Auto-detect project type, framework, dependencies |
| 1-2 | Setup Wizard | Interactive `agenttree init` with smart defaults |
| 2 | Template Library | Pre-built templates for Django/Next.js/FastAPI/etc |
| 2 | Validation | Health checks before dispatch |
| 3 | First-Run UX | Guided first dispatch experience |
| 3 | Diagnostics | `agenttree doctor` command |

**Total: 3 weeks**

---

## Success Metrics

- ⏱️ Time to first working dispatch: **< 2 minutes**
- 📉 Setup failure rate: **< 5%**
- 😊 User doesn't need to read docs: **Yes**
- 🎯 Works out-of-box for top 10 frameworks: **Yes**

---

## Alternative: Zero-Config Mode

For users who just want to try it:

```bash
# Absolute zero config
agenttree quick-start "Add a dark mode toggle"

# Does everything:
# - Creates temp worktree
# - Auto-detects project
# - Runs agent
# - Shows live output
# - Cleans up after

# Perfect for one-off tasks
```

---

## Files Created

After `agenttree init`:

```
.agenttree/
├── config.yaml          # User configuration
├── setup.sh             # Generated setup script
├── state.json           # Internal state
└── agents/
    ├── agent-1/         # Metadata per agent
    ├── agent-2/
    └── agent-3/

AGENTS.md                # Instructions for AI tools
.gitignore               # Updated with agent patterns
```

---

## Config File Format

```yaml
# .agenttree/config.yaml
project: myapp
worktrees_dir: ~/Projects/worktrees
port_base: 8001

ai_tool: claude

num_agents: 3

# Project-specific
python_version: "3.11"
venv_type: venv
copy_env: true
env_template: .env.example

docker_services:
  - postgres
  - redis

# Custom setup
custom_setup: |
  python manage.py migrate
  python manage.py loaddata fixtures/dev.json
```

---

## Next Steps

1. Build detection system first (most value)
2. Create basic wizard (80% of use cases)
3. Add validation (prevents frustration)
4. Polish first-run UX
5. Add templates and diagnostics

The key is making the **happy path trivial** while still allowing customization for power users.
