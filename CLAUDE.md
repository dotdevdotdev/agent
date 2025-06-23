# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an Agentic GitHub Issue Response System - an AI-powered FastAPI application that automatically responds to GitHub issues by leveraging the Claude Code CLI tool for code analysis and generation. The system creates isolated git worktrees for each issue and processes them asynchronously.

## Development Commands

### Environment Setup
```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Setup environment
cp .env.example .env
# Edit .env with your configuration

# Setup GitHub labels (requires gh CLI and authentication)
./scripts/setup-github-labels.sh
```

### Running the Application
```bash
# Start the server (development mode with auto-reload)
python main.py

# Or use the start script
./scripts/start_server.sh
```

### Testing
```bash
# Run tests (no specific test runner configured - use pytest by default)
pytest tests/
```

### GitHub Integration Setup
```bash
# Install GitHub CLI
# See: https://cli.github.com/

# Authenticate with GitHub
gh auth login

# Create repository labels for agent workflow
./scripts/setup-github-labels.sh

# Configure repository secrets (via GitHub web interface):
# - AGENT_WEBHOOK_URL: Your server webhook endpoint
# - AGENT_WEBHOOK_SECRET: Webhook signature secret
```

## Architecture

### Core Components

**FastAPI Application** (`main.py`):
- Runs on port 8080 by default
- Includes health, webhook, and jobs routers
- Uses structured logging with structlog

**Job Management System** (`src/services/job_manager.py`):
- In-memory job tracking (development only - needs Redis/PostgreSQL for production)
- Manages long-running AI processing tasks
- Supports job status tracking, cancellation, and logging
- Implements cleanup for old completed jobs

**GitHub Integration** (`src/services/github_client.py`):
- Comprehensive GitHub API client with rate limiting
- Agent-specific workflow methods (start_agent_task, complete_agent_task, etc.)
- Bidirectional communication via comments and labels
- Error handling and retry logic

**Data Models**:
- `src/models/jobs.py`: Job lifecycle management (pending → running → completed/failed/cancelled)
- `src/models/github.py`: GitHub API and webhook payload models

**API Endpoints**:
- `GET /health`: Health check
- `POST /webhook/github`: GitHub issue webhook receiver
- `GET /jobs/{job_id}`: Job status monitoring

**GitHub Integration**:
- `.github/ISSUE_TEMPLATE/agent-task.yml`: Structured issue forms for task submission
- `.github/workflows/agent-dispatcher.yml`: GitHub Actions workflow for webhook dispatch
- Agent state machine using labels: queued → in-progress → completed/failed

### Issue-Ops Workflow
1. **Issue Creation**: User creates GitHub issue using agent task template
2. **Auto-Dispatch**: GitHub Actions workflow validates and sends webhook to agent server
3. **Job Creation**: Agent server creates background job and updates issue with `agent:in-progress` label
4. **Worktree Setup**: System creates isolated git worktree for the issue
5. **AI Processing**: Claude Code CLI analyzes issue and generates solutions
6. **Result Delivery**: Agent posts results via GitHub comments and updates labels
7. **Cleanup**: Worktree removed and issue marked `agent:completed`

### Key Services
- **Webhook Handler**: Processes GitHub issue events and GitHub Actions dispatches
- **Job Manager**: Tracks async AI processing jobs with state management
- **GitHub Client**: Comprehensive API integration for comments, labels, and issues
- **Git Service**: Manages worktree isolation for sandboxed processing
- **Claude Service**: CLI integration and monitoring

## Configuration

Environment variables in `.env` (copy from `.env.example`):
- `GITHUB_WEBHOOK_SECRET`: GitHub webhook validation secret
- `GITHUB_TOKEN`: Personal access token for GitHub API
- `REPO_OWNER`/`REPO_NAME`: Target repository details
- `CLAUDE_CODE_PATH`: Path to claude CLI tool (default: "claude")
- `CLAUDE_TIMEOUT`: Max execution time (default: 3600 seconds)
- `MAX_CONCURRENT_JOBS`: Concurrent processing limit (default: 3)

## File Structure

```
.github/
├── ISSUE_TEMPLATE/    # GitHub issue forms for task submission
└── workflows/         # GitHub Actions for webhook dispatch

src/
├── api/               # FastAPI route handlers
├── core/              # Core business logic
├── models/            # Pydantic data models
├── services/          # Service layer (job management, GitHub API, external APIs)
└── utils/             # Utility functions

config/                # Application configuration
docs/                  # Documentation (labels, workflow guides)
scripts/               # Setup and utility scripts
tests/                 # Test suite
tasks/                 # Task management and communication
worktrees/             # Git worktree isolation (created at runtime)
```

## Development Notes

- Uses FastAPI with uvicorn server
- Structured logging with JSON output
- Git worktrees for sandboxed processing
- Job status tracking with progress updates
- Webhook signature validation for security
- CORS configured for development (all origins) vs production (localhost:3000)