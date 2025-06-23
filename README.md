# Agentic GitHub Issue Response System

An intelligent AI-powered system that automatically responds to GitHub issues by leveraging the Claude Code CLI tool for code analysis and generation.

## Overview

This system creates an automated workflow that:

1. **Listens for GitHub Issues**: Receives webhook notifications when new issues are created
2. **AI Analysis**: Uses Claude Code CLI to analyze the issue and generate solutions
3. **Sandboxed Processing**: Creates isolated git worktrees for each issue to prevent conflicts
4. **Automated Responses**: Updates GitHub issues with AI-generated solutions and code changes

## Features

- 🚀 **FastAPI-based webhook server** running on port 8080
- 🤖 **Claude Code CLI integration** for AI-powered analysis
- 🔒 **Sandboxed execution** using git worktrees
- 📊 **Job monitoring and status tracking**
- 🔐 **GitHub webhook signature validation**
- 📝 **Comprehensive logging and error handling**

## Project Structure

```
agent/
├── project-planning/     # Project documentation and specs
├── research/            # Research materials and references
├── tasks/              # Task management and communication
│   ├── users/          # User-facing communications
│   └── agents/         # Agent-to-agent communications
├── src/                # Main application source code
│   ├── api/            # FastAPI routes and endpoints
│   ├── core/           # Core business logic
│   ├── models/         # Data models and schemas
│   ├── services/       # Service layer (GitHub, CLI)
│   └── utils/          # Utility functions
├── config/             # Configuration files
├── tests/              # Test suite
└── scripts/            # Utility scripts
```

## Quick Start

### Prerequisites

- Python 3.9+
- Git
- Claude Code CLI tool installed and configured
- GitHub personal access token

### Installation

1. **Clone the repository**

   ```bash
   git clone <repository-url>
   cd agent
   ```

2. **Create virtual environment**

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**

   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

5. **Run the server**
   ```bash
   python main.py
   ```

The server will start on `http://localhost:8080`

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure:

- **GitHub Settings**:

  - `GITHUB_WEBHOOK_SECRET`: Secret for webhook validation
  - `GITHUB_TOKEN`: Personal access token for GitHub API
  - `REPO_OWNER` & `REPO_NAME`: Target repository details

- **Server Settings**:

  - `PORT`: Server port (default: 8080)
  - `HOST`: Server host (default: 0.0.0.0)
  - `DEBUG`: Enable debug mode

- **Claude CLI**:
  - `CLAUDE_CODE_PATH`: Path to claude CLI tool
  - `CLAUDE_TIMEOUT`: Maximum execution time

### GitHub Webhook Setup

1. Go to your repository settings
2. Navigate to Webhooks
3. Add webhook with URL: `http://your-server:8080/webhook/github`
4. Select "Issues" events
5. Set the secret from your `.env` file

## API Endpoints

### Health Check

```
GET /health
```

Returns server health status

### GitHub Webhook

```
POST /webhook/github
```

Receives GitHub issue webhooks

### Job Status

```
GET /jobs/{job_id}
```

Check the status of a processing job

## Development

### Running Tests

```bash
pytest tests/
```

### Development Mode

```bash
python main.py
# Server runs with auto-reload enabled
```

### Adding New Features

1. Create feature branch: `git checkout -b feature/your-feature`
2. Implement changes in appropriate `src/` directories
3. Add tests in `tests/`
4. Update documentation as needed

## Architecture

### Workflow

1. **Webhook Reception**: FastAPI server receives GitHub issue webhook
2. **Validation**: Verify webhook signature and extract issue data
3. **Job Creation**: Create background job for processing
4. **Worktree Setup**: Create isolated git worktree for the issue
5. **AI Processing**: Run Claude Code CLI tool to analyze and generate solutions
6. **Result Handling**: Update GitHub issue with results
7. **Cleanup**: Remove worktree and update job status

### Key Components

- **Webhook Handler**: Processes incoming GitHub webhooks
- **Job Manager**: Manages long-running AI processing jobs
- **Git Service**: Handles worktree creation and management
- **GitHub Service**: API integration for updating issues
- **Claude Service**: CLI tool integration and monitoring

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## License

[Add your license here]

## Support

For questions or issues, please create a GitHub issue or contact the development team.
