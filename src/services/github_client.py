"""
Enhanced GitHub API client for agent operations
"""

import asyncio
import httpx
import structlog
from typing import List, Dict, Any, Optional, Union
from datetime import datetime, timedelta
from config.settings import settings
from src.models.github import GitHubIssue, GitHubIssueComment

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
        try:
            await self.remove_label(repo_full_name, issue_number, "agent:queued")
        except GitHubAPIError:
            pass  # Label might not exist
        
        await self.add_labels(repo_full_name, issue_number, ["agent:in-progress"])

        await self.create_comment(
            repo_full_name,
            issue_number,
            "🤖 **Agent Started**\n\nI'm now processing your request. I'll update you on my progress..."
        )

    async def request_feedback(self, repo_full_name: str, issue_number: int, feedback_request: str) -> None:
        """Request feedback from user"""
        try:
            await self.remove_label(repo_full_name, issue_number, "agent:in-progress")
        except GitHubAPIError:
            pass  # Label might not exist
        
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