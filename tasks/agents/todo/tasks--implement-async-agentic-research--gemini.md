# Phase 1: Core Infrastructure Implementation Tasks

## Mission Objective

Transform the current FastAPI foundation into a GitHub-integrated async agentic system by implementing core infrastructure components that enable Issue-Ops workflow.

## Phase Overview

This phase establishes the GitHub integration layer that allows users to submit tasks via GitHub issues and enables the agent to communicate back through comments and labels.

---

## Task 1.1: GitHub Issue Templates Setup

### Objective

Create structured GitHub Issue Forms for task submission that enable users to submit standardized agent tasks through the GitHub UI.

### Technical Requirements

- YAML-based GitHub issue template with form validation
- Structured fields for task type, prompt, and file references
- Auto-labeling with `agent:queued` status
- Form validation to ensure required fields

### Implementation Steps

1. **Create GitHub issue template directory**

   ```bash
   mkdir -p .github/ISSUE_TEMPLATE
   ```

2. **Create agent task template file**: `.github/ISSUE_TEMPLATE/agent-task.yml`

   ```yaml
   name: 🤖 New Agent Task
   description: Assign a new task to the Claude-powered agent.
   title: "[AGENT]: "
   labels: ["agent:queued"]
   body:
     - type: markdown
       attributes:
         value: |
           ## Task Submission Form
           Please fill out the details below to queue a new task for the AI agent.

     - type: dropdown
       id: task-type
       attributes:
         label: Task Type
         description: Select the primary capability you want the agent to use.
         options:
           - "Code Analysis"
           - "Documentation Generation"
           - "Code Refactoring"
           - "Research and Summarization"
           - "General Question"
           - "Bug Investigation"
           - "Feature Implementation"
           - "Code Review"
       validations:
         required: true

     - type: dropdown
       id: priority
       attributes:
         label: Priority Level
         description: How urgent is this task?
         options:
           - "Low"
           - "Medium"
           - "High"
           - "Critical"
         default: 1
       validations:
         required: true

     - type: textarea
       id: prompt
       attributes:
         label: Detailed Prompt
         description: "Provide the full prompt for the agent. Be specific about what you want accomplished."
         placeholder: "Example: Please analyze the performance of the `calculate_metrics` function and suggest optimizations..."
       validations:
         required: true

     - type: input
       id: relevant-files
       attributes:
         label: Relevant Files or URLs
         description: "Optional. Comma-separated list of file paths or URLs to focus on."
         placeholder: "e.g., src/main.py, docs/architecture.md, https://github.com/owner/repo/issues/123"

     - type: textarea
       id: context
       attributes:
         label: Additional Context
         description: "Any additional context, constraints, or requirements."
         placeholder: "Background information, constraints, expected outcomes..."

     - type: dropdown
       id: output-format
       attributes:
         label: Preferred Output Format
         description: How would you like the results delivered?
         options:
           - "Code changes with explanations"
           - "Analysis report"
           - "Documentation updates"
           - "Implementation plan"
           - "Bug fix with tests"
         default: 0

     - type: checkboxes
       id: acknowledgements
       attributes:
         label: Acknowledgements
         options:
           - label: I understand this task will be processed by an AI agent.
             required: true
           - label: I have provided sufficient detail for the agent to complete this task.
             required: true
   ```

### Acceptance Criteria

- [ ] Users can create new issues using the structured form
- [ ] Form validates required fields before submission
- [ ] Issues are automatically labeled with `agent:queued`
- [ ] All form fields are properly captured in issue body

### Dependencies

None

### Estimated Complexity

Simple (2-4 hours)

---

## Task 1.2: GitHub Actions Workflow Creation

### Objective

Create GitHub Actions workflow that triggers agent processing when issues are created or updated, establishing the automation bridge between GitHub events and the agent server.

### Technical Requirements

- Workflow triggers on issue events (opened, labeled, commented)
- Sends webhook payload to agent server
- Handles authentication and error scenarios
- Supports both development and production environments

### Implementation Steps

1. **Create GitHub workflows directory**

   ```bash
   mkdir -p .github/workflows
   ```

2. **Create agent dispatcher workflow**: `.github/workflows/agent-dispatcher.yml`

   ```yaml
   name: 🤖 Agent Task Dispatcher

   on:
     issues:
       types: [opened, labeled, closed]
     issue_comment:
       types: [created]

   jobs:
     dispatch-to-agent:
       runs-on: ubuntu-latest
       if: |
         (github.event.action == 'opened' && contains(github.event.issue.labels.*.name, 'agent:queued')) ||
         (github.event.action == 'labeled' && github.event.label.name == 'agent:queued') ||
         (github.event.action == 'created' && contains(github.event.issue.labels.*.name, 'agent:in-progress'))

       steps:
         - name: Validate Issue Template
           id: validate
           run: |
             # Check if issue uses agent template
             if [[ "${{ github.event.issue.body }}" == *"Task Type"* ]]; then
               echo "valid=true" >> $GITHUB_OUTPUT
             else
               echo "valid=false" >> $GITHUB_OUTPUT
             fi

         - name: Send Webhook to Agent Server
           if: steps.validate.outputs.valid == 'true'
           env:
             AGENT_WEBHOOK_URL: ${{ secrets.AGENT_WEBHOOK_URL }}
             AGENT_WEBHOOK_SECRET: ${{ secrets.AGENT_WEBHOOK_SECRET }}
           run: |
             # Prepare webhook payload
             payload=$(jq -n \
               --arg event_type "${{ github.event_name }}" \
               --arg action "${{ github.event.action }}" \
               --argjson issue '${{ toJson(github.event.issue) }}' \
               --argjson comment '${{ toJson(github.event.comment) }}' \
               --argjson repository '${{ toJson(github.event.repository) }}' \
               '{
                 event_type: $event_type,
                 action: $action,
                 issue: $issue,
                 comment: $comment,
                 repository: $repository,
                 timestamp: now
               }')

             # Generate HMAC signature
             signature=$(echo -n "$payload" | openssl dgst -sha256 -hmac "$AGENT_WEBHOOK_SECRET" -binary | base64)

             # Send webhook
             curl -X POST "$AGENT_WEBHOOK_URL" \
               -H "Content-Type: application/json" \
               -H "X-Hub-Signature-256: sha256=$signature" \
               -H "X-GitHub-Event: ${{ github.event_name }}" \
               -H "User-Agent: GitHub-Hookshot/agent-dispatcher" \
               -d "$payload" \
               --fail-with-body

         - name: Handle Webhook Failure
           if: failure()
           run: |
             # Comment on issue if webhook fails
             gh issue comment ${{ github.event.issue.number }} \
               --body "⚠️ **Agent Dispatch Failed**

             The agent server could not be reached. Please check:
             - Agent server is running
             - Webhook URL is configured correctly
             - Network connectivity is available

             You can retry by removing and re-adding the \`agent:queued\` label."
           env:
             GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}

     notify-agent-unavailable:
       runs-on: ubuntu-latest
       if: |
         github.event.action == 'opened' && 
         contains(github.event.issue.labels.*.name, 'agent:queued') &&
         !secrets.AGENT_WEBHOOK_URL

       steps:
         - name: Comment on Issue
           run: |
             gh issue comment ${{ github.event.issue.number }} \
               --body "🚧 **Agent Server Not Configured**

             The agent server webhook URL is not configured. Please contact an administrator to set up the agent infrastructure.

             Required repository secrets:
             - \`AGENT_WEBHOOK_URL\`: The URL of the agent server
             - \`AGENT_WEBHOOK_SECRET\`: Webhook signature secret"
           env:
             GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
   ```

### Acceptance Criteria

- [ ] Workflow triggers on appropriate issue events
- [ ] Webhook payload is sent to agent server with proper authentication
- [ ] Error handling provides clear feedback to users
- [ ] Only processes issues with agent template format

### Dependencies

- Task 1.1 (GitHub Issue Templates)
- Agent server webhook endpoint (from existing implementation)

### Estimated Complexity

Simple (3-5 hours)

---

## Task 1.3: GitHub Labels Setup

### Objective

Define and document the label-based state machine for agent workflow tracking, enabling clear visual status of agent tasks.

### Technical Requirements

- Standardized label names and colors for agent states
- Clear documentation of state transitions
- Labels support the complete agent workflow lifecycle

### Implementation Steps

1. **Create labels documentation**: `docs/github-labels.md`

   ````markdown
   # GitHub Labels for Agent Workflow

   ## Agent State Labels

   | Label                     | Color     | Description                             | Next States                                                  |
   | ------------------------- | --------- | --------------------------------------- | ------------------------------------------------------------ |
   | `agent:queued`            | `#FFA500` | Task is waiting for agent to pick up    | `agent:in-progress`, `agent:failed`                          |
   | `agent:in-progress`       | `#1E90FF` | Agent is actively working on the task   | `agent:awaiting-feedback`, `agent:completed`, `agent:failed` |
   | `agent:awaiting-feedback` | `#9370DB` | Agent needs user input or clarification | `agent:in-progress`, `agent:completed`                       |
   | `agent:completed`         | `#32CD32` | Task successfully completed by agent    | Final state                                                  |
   | `agent:failed`            | `#DC143C` | Task failed or encountered error        | `agent:queued` (for retry)                                   |

   ## Priority Labels

   | Label               | Color     | Description            |
   | ------------------- | --------- | ---------------------- |
   | `priority:low`      | `#90EE90` | Low priority task      |
   | `priority:medium`   | `#FFD700` | Medium priority task   |
   | `priority:high`     | `#FF6347` | High priority task     |
   | `priority:critical` | `#FF0000` | Critical priority task |

   ## Task Type Labels

   | Label                | Color     | Description                          |
   | -------------------- | --------- | ------------------------------------ |
   | `type:code-analysis` | `#E6E6FA` | Code analysis and review tasks       |
   | `type:documentation` | `#F0E68C` | Documentation generation and updates |
   | `type:refactoring`   | `#DDA0DD` | Code refactoring and optimization    |
   | `type:research`      | `#98FB98` | Research and investigation tasks     |
   | `type:bug-fix`       | `#FFB6C1` | Bug investigation and fixes          |
   | `type:feature`       | `#87CEEB` | Feature implementation               |

   ## Label Management Commands

   ```bash
   # Create all agent labels (run from repository root)
   gh label create "agent:queued" --color "FFA500" --description "Task is queued for agent processing"
   gh label create "agent:in-progress" --color "1E90FF" --description "Agent is actively working on this task"
   gh label create "agent:awaiting-feedback" --color "9370DB" --description "Agent is waiting for user feedback"
   gh label create "agent:completed" --color "32CD32" --description "Task completed successfully by agent"
   gh label create "agent:failed" --color "DC143C" --description "Task failed or encountered an error"

   gh label create "priority:low" --color "90EE90" --description "Low priority task"
   gh label create "priority:medium" --color "FFD700" --description "Medium priority task"
   gh label create "priority:high" --color "FF6347" --description "High priority task"
   gh label create "priority:critical" --color "FF0000" --description "Critical priority task"

   gh label create "type:code-analysis" --color "E6E6FA" --description "Code analysis and review"
   gh label create "type:documentation" --color "F0E68C" --description "Documentation tasks"
   gh label create "type:refactoring" --color "DDA0DD" --description "Code refactoring"
   gh label create "type:research" --color "98FB98" --description "Research and investigation"
   gh label create "type:bug-fix" --color "FFB6C1" --description "Bug fixes"
   gh label create "type:feature" --color "87CEEB" --description "Feature implementation"
   ```
   ````

   ## State Machine Diagram

   ```
   agent:queued
        ↓
   agent:in-progress ← → agent:awaiting-feedback
        ↓                      ↓
   agent:completed        agent:completed
        ↓                      ↓
   [CLOSED]               [CLOSED]

   Any state → agent:failed → agent:queued (retry)
   ```

   ```

   ```

2. **Create label setup script**: `scripts/setup-github-labels.sh`

   ```bash
   #!/bin/bash
   # Setup GitHub labels for agent workflow

   set -e

   echo "🏷️  Setting up GitHub labels for agent workflow..."

   # Check if gh CLI is installed
   if ! command -v gh &> /dev/null; then
       echo "❌ GitHub CLI (gh) is not installed. Please install it first."
       exit 1
   fi

   # Check if authenticated
   if ! gh auth status &> /dev/null; then
       echo "❌ Not authenticated with GitHub. Please run 'gh auth login' first."
       exit 1
   fi

   # Create agent state labels
   echo "Creating agent state labels..."
   gh label create "agent:queued" --color "FFA500" --description "Task is queued for agent processing" --force
   gh label create "agent:in-progress" --color "1E90FF" --description "Agent is actively working on this task" --force
   gh label create "agent:awaiting-feedback" --color "9370DB" --description "Agent is waiting for user feedback" --force
   gh label create "agent:completed" --color "32CD32" --description "Task completed successfully by agent" --force
   gh label create "agent:failed" --color "DC143C" --description "Task failed or encountered an error" --force

   # Create priority labels
   echo "Creating priority labels..."
   gh label create "priority:low" --color "90EE90" --description "Low priority task" --force
   gh label create "priority:medium" --color "FFD700" --description "Medium priority task" --force
   gh label create "priority:high" --color "FF6347" --description "High priority task" --force
   gh label create "priority:critical" --color "FF0000" --description "Critical priority task" --force

   # Create task type labels
   echo "Creating task type labels..."
   gh label create "type:code-analysis" --color "E6E6FA" --description "Code analysis and review" --force
   gh label create "type:documentation" --color "F0E68C" --description "Documentation tasks" --force
   gh label create "type:refactoring" --color "DDA0DD" --description "Code refactoring" --force
   gh label create "type:research" --color "98FB98" --description "Research and investigation" --force
   gh label create "type:bug-fix" --color "FFB6C1" --description "Bug fixes" --force
   gh label create "type:feature" --color "87CEEB" --description "Feature implementation" --force

   echo "✅ All labels created successfully!"
   echo "📖 See docs/github-labels.md for usage information."
   ```

3. **Make script executable**
   ```bash
   chmod +x scripts/setup-github-labels.sh
   ```

### Acceptance Criteria

- [ ] All required labels exist with proper colors and descriptions
- [ ] State machine transitions are clearly documented
- [ ] Setup script successfully creates all labels
- [ ] Labels integrate with issue template defaults

### Dependencies

None

### Estimated Complexity

Simple (1-2 hours)

---

## Task 1.4: Enhanced GitHub API Client

### Objective

Create comprehensive GitHub API client for bidirectional communication that enables the agent to interact with GitHub issues, comments, and labels.

### Technical Requirements

- Async HTTP client with proper authentication
- Full CRUD operations for issues, comments, and labels
- Error handling and retry logic
- Rate limiting compliance
- Support for GitHub API v3 and v4 (GraphQL)

### Implementation Steps

1. **Update requirements.txt**

   ```
   httpx==0.25.2
   aiofiles==23.2.0
   ```

2. **Create GitHub API client**: `src/services/github_client.py`

   ```python
   import asyncio
   import httpx
   import structlog
   from typing import List, Dict, Any, Optional, Union
   from datetime import datetime, timedelta
   from config.settings import settings
   from src.models.github import GitHubIssue, GitHubComment

   logger = structlog.get_logger()

   class GitHubAPIError(Exception):
       """Custom exception for GitHub API errors"""
       def __init__(self, message: str, status_code: int = None, response_data: dict = None):
           self.message = message
           self.status_code = status_code
           self.response_data = response_data
           super().__init__(message)

   class GitHubClient:
       """GitHub API client for agent operations"""

       def __init__(self, token: str = None):
           self.token = token or settings.GITHUB_TOKEN
           if not self.token:
               raise ValueError("GitHub token is required")

           self.headers = {
               "Authorization": f"token {self.token}",
               "Accept": "application/vnd.github.v3+json",
               "User-Agent": "Agentic-GitHub-Agent/1.0"
           }
           self.client = httpx.AsyncClient(
               headers=self.headers,
               timeout=httpx.Timeout(30.0),
               limits=httpx.Limits(max_connections=10, max_keepalive_connections=5)
           )
           self.rate_limit_remaining = 5000
           self.rate_limit_reset = datetime.now()

       async def __aenter__(self):
           return self

       async def __aexit__(self, exc_type, exc_val, exc_tb):
           await self.client.aclose()

       async def _make_request(self, method: str, url: str, **kwargs) -> Dict[Any, Any]:
           """Make an authenticated request to GitHub API with error handling"""

           # Check rate limit
           if self.rate_limit_remaining <= 10 and datetime.now() < self.rate_limit_reset:
               wait_time = (self.rate_limit_reset - datetime.now()).total_seconds()
               logger.warning("Rate limit approaching, waiting", wait_time=wait_time)
               await asyncio.sleep(wait_time)

           try:
               response = await self.client.request(method, url, **kwargs)

               # Update rate limit info
               self.rate_limit_remaining = int(response.headers.get("X-RateLimit-Remaining", 5000))
               reset_timestamp = int(response.headers.get("X-RateLimit-Reset", 0))
               if reset_timestamp:
                   self.rate_limit_reset = datetime.fromtimestamp(reset_timestamp)

               if response.status_code >= 400:
                   error_data = {}
                   try:
                       error_data = response.json()
                   except:
                       pass

                   raise GitHubAPIError(
                       f"GitHub API error: {response.status_code}",
                       status_code=response.status_code,
                       response_data=error_data
                   )

               return response.json() if response.content else {}

           except httpx.RequestError as e:
               logger.error("GitHub API request failed", error=str(e), url=url)
               raise GitHubAPIError(f"Request failed: {str(e)}")

       # Issue Operations
       async def get_issue(self, repo_full_name: str, issue_number: int) -> Dict[str, Any]:
           """Get a specific issue"""
           url = f"{settings.GITHUB_API_URL}/repos/{repo_full_name}/issues/{issue_number}"
           return await self._make_request("GET", url)

       async def update_issue(self, repo_full_name: str, issue_number: int, **kwargs) -> Dict[str, Any]:
           """Update an issue (title, body, state, labels, etc.)"""
           url = f"{settings.GITHUB_API_URL}/repos/{repo_full_name}/issues/{issue_number}"
           return await self._make_request("PATCH", url, json=kwargs)

       # Comment Operations
       async def create_comment(self, repo_full_name: str, issue_number: int, body: str) -> Dict[str, Any]:
           """Create a comment on an issue"""
           url = f"{settings.GITHUB_API_URL}/repos/{repo_full_name}/issues/{issue_number}/comments"
           data = {"body": body}
           return await self._make_request("POST", url, json=data)

       async def update_comment(self, repo_full_name: str, comment_id: int, body: str) -> Dict[str, Any]:
           """Update an existing comment"""
           url = f"{settings.GITHUB_API_URL}/repos/{repo_full_name}/issues/comments/{comment_id}"
           data = {"body": body}
           return await self._make_request("PATCH", url, json=data)

       async def get_comments(self, repo_full_name: str, issue_number: int) -> List[Dict[str, Any]]:
           """Get all comments for an issue"""
           url = f"{settings.GITHUB_API_URL}/repos/{repo_full_name}/issues/{issue_number}/comments"
           return await self._make_request("GET", url)

       # Label Operations
       async def add_labels(self, repo_full_name: str, issue_number: int, labels: List[str]) -> Dict[str, Any]:
           """Add labels to an issue"""
           url = f"{settings.GITHUB_API_URL}/repos/{repo_full_name}/issues/{issue_number}/labels"
           data = {"labels": labels}
           return await self._make_request("POST", url, json=data)

       async def remove_label(self, repo_full_name: str, issue_number: int, label: str) -> None:
           """Remove a specific label from an issue"""
           url = f"{settings.GITHUB_API_URL}/repos/{repo_full_name}/issues/{issue_number}/labels/{label}"
           await self._make_request("DELETE", url)

       async def replace_labels(self, repo_full_name: str, issue_number: int, labels: List[str]) -> Dict[str, Any]:
           """Replace all labels on an issue"""
           url = f"{settings.GITHUB_API_URL}/repos/{repo_full_name}/issues/{issue_number}/labels"
           data = {"labels": labels}
           return await self._make_request("PUT", url, json=data)

       # Repository Operations
       async def get_repository(self, repo_full_name: str) -> Dict[str, Any]:
           """Get repository information"""
           url = f"{settings.GITHUB_API_URL}/repos/{repo_full_name}"
           return await self._make_request("GET", url)

       async def get_file_content(self, repo_full_name: str, file_path: str, ref: str = "main") -> Dict[str, Any]:
           """Get file content from repository"""
           url = f"{settings.GITHUB_API_URL}/repos/{repo_full_name}/contents/{file_path}?ref={ref}"
           return await self._make_request("GET", url)

       # Agent-specific helper methods
       async def start_agent_task(self, repo_full_name: str, issue_number: int) -> None:
           """Mark an issue as being processed by the agent"""
           await self.remove_label(repo_full_name, issue_number, "agent:queued")
           await self.add_labels(repo_full_name, issue_number, ["agent:in-progress"])

           await self.create_comment(
               repo_full_name,
               issue_number,
               "🤖 **Agent Started**\n\nI'm now processing your request. I'll update you on my progress..."
           )

       async def request_feedback(self, repo_full_name: str, issue_number: int, feedback_request: str) -> None:
           """Request feedback from user"""
           await self.remove_label(repo_full_name, issue_number, "agent:in-progress")
           await self.add_labels(repo_full_name, issue_number, ["agent:awaiting-feedback"])

           comment_body = f"🤔 **Feedback Requested**\n\n{feedback_request}\n\n*Please reply with your feedback to continue processing.*"
           await self.create_comment(repo_full_name, issue_number, comment_body)

       async def complete_agent_task(self, repo_full_name: str, issue_number: int, result: str, close_issue: bool = True) -> None:
           """Mark task as completed and provide results"""
           # Remove progress labels
           current_labels = ["agent:in-progress", "agent:awaiting-feedback"]
           for label in current_labels:
               try:
                   await self.remove_label(repo_full_name, issue_number, label)
               except GitHubAPIError:
                   pass  # Label might not exist

           await self.add_labels(repo_full_name, issue_number, ["agent:completed"])

           comment_body = f"✅ **Task Completed**\n\n{result}\n\n*This task has been completed successfully.*"
           await self.create_comment(repo_full_name, issue_number, comment_body)

           if close_issue:
               await self.update_issue(repo_full_name, issue_number, state="closed")

       async def fail_agent_task(self, repo_full_name: str, issue_number: int, error: str, retryable: bool = True) -> None:
           """Mark task as failed with error information"""
           # Remove progress labels
           current_labels = ["agent:in-progress", "agent:awaiting-feedback"]
           for label in current_labels:
               try:
                   await self.remove_label(repo_full_name, issue_number, label)
               except GitHubAPIError:
                   pass

           await self.add_labels(repo_full_name, issue_number, ["agent:failed"])

           retry_text = "\n\n*You can retry this task by re-adding the `agent:queued` label.*" if retryable else ""
           comment_body = f"❌ **Task Failed**\n\n{error}{retry_text}"
           await self.create_comment(repo_full_name, issue_number, comment_body)

       async def update_progress(self, repo_full_name: str, issue_number: int, progress_message: str) -> None:
           """Update progress with a new comment"""
           comment_body = f"🔄 **Progress Update**\n\n{progress_message}"
           await self.create_comment(repo_full_name, issue_number, comment_body)
   ```

3. **Update settings**: Add to `config/settings.py`
   ```python
   # Add to existing settings
   GITHUB_API_URL: str = Field(default="https://api.github.com", description="GitHub API base URL")
   GITHUB_TOKEN: str = Field(..., description="GitHub personal access token")
   ```

### Acceptance Criteria

- [ ] Can authenticate with GitHub API using token
- [ ] Successfully creates, updates, and deletes comments
- [ ] Can add, remove, and replace labels on issues
- [ ] Handles rate limiting gracefully
- [ ] Provides clear error messages for API failures
- [ ] Includes agent-specific helper methods for workflow

### Dependencies

None

### Estimated Complexity

Medium (6-8 hours)

---

## Phase 1 Integration Testing

### Test Plan

1. **GitHub Issue Template Test**

   - Create a new issue using the agent template
   - Verify all form fields are properly captured
   - Confirm issue is automatically labeled with `agent:queued`

2. **GitHub Actions Workflow Test**

   - Trigger workflow by creating agent issue
   - Verify webhook is sent to agent server
   - Test error handling when agent server is unavailable

3. **GitHub API Client Test**

   - Test comment creation and updates
   - Test label operations (add, remove, replace)
   - Test rate limiting behavior
   - Test error handling for various API failures

4. **End-to-End Test**
   - Create issue with agent template
   - Verify workflow triggers and sends webhook
   - Test agent server receives and processes webhook
   - Verify GitHub API client can respond with comments/labels

### Post-Implementation Tasks

1. **Documentation Updates**

   - Update README with setup instructions
   - Document environment variables needed
   - Create user guide for issue submission

2. **Security Review**

   - Verify webhook signature validation
   - Review GitHub token permissions
   - Test authentication error scenarios

3. **Repository Secrets Setup**
   - `AGENT_WEBHOOK_URL`: Agent server webhook endpoint
   - `AGENT_WEBHOOK_SECRET`: Webhook signature secret
   - Personal access token with repo scope

---

## Next Phase Preview

After completing Phase 1, the next implementation phase will focus on:

- **Phase 2: GitHub Integration** - Issue form parsing, enhanced webhook processing, agent state machine
- **Phase 3: Claude CLI Integration** - Worktree management, Claude service layer, agent instruction templates

Phase 1 establishes the foundation for GitHub-based task submission and basic agent-to-GitHub communication, enabling the full Issue-Ops workflow in subsequent phases.

---

## Success Metrics

- [ ] Users can submit structured tasks via GitHub issues
- [ ] GitHub Actions workflow automatically triggers agent processing
- [ ] Agent can communicate back to GitHub via comments and labels
- [ ] All error scenarios are handled gracefully with user feedback
- [ ] Complete audit trail of agent activities via GitHub interface

This completes Phase 1 of the async agentic system implementation, establishing the core GitHub integration infrastructure needed for the Issue-Ops workflow.
