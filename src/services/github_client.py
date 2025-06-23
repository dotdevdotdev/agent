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

    # Phase 2 Enhanced Agent Methods
    async def add_label(self, repo_full_name: str, issue_number: int, label: str) -> None:
        """Add a single label to an issue"""
        await self.add_labels(repo_full_name, issue_number, [label])

    async def transition_agent_state(self, repo_full_name: str, issue_number: int,
                                   from_state: str, to_state: str, 
                                   progress_message: str) -> None:
        """Transition agent state with label updates and progress comment"""
        logger.info(
            "Transitioning agent state",
            repo=repo_full_name,
            issue=issue_number,
            from_state=from_state,
            to_state=to_state
        )

        try:
            # Remove old state label if it exists
            if from_state:
                try:
                    await self.remove_label(repo_full_name, issue_number, from_state)
                except GitHubAPIError:
                    pass  # Label might not exist

            # Add new state label
            await self.add_label(repo_full_name, issue_number, to_state)

            # Create progress comment
            if progress_message:
                emoji_map = {
                    "agent:queued": "⏳",
                    "agent:validating": "🔍",
                    "agent:analyzing": "🧠",
                    "agent:in-progress": "⚙️",
                    "agent:implementing": "🛠️",
                    "agent:testing": "🧪",
                    "agent:awaiting-feedback": "❓",
                    "agent:completed": "✅",
                    "agent:failed": "❌",
                    "agent:cancelled": "🚫",
                    "agent:escalated": "🚨"
                }
                
                emoji = emoji_map.get(to_state, "🤖")
                comment_body = f"{emoji} **State Update**: {to_state}\n\n{progress_message}"
                await self.create_comment(repo_full_name, issue_number, comment_body)

        except Exception as e:
            logger.error(
                "Failed to transition agent state",
                error=str(e),
                repo=repo_full_name,
                issue=issue_number
            )
            raise

    async def create_progress_thread(self, repo_full_name: str, issue_number: int,
                                   thread_title: str, updates: List[str]) -> None:
        """Create a threaded progress update"""
        try:
            comment_parts = [f"## 📈 {thread_title}"]
            
            for i, update in enumerate(updates, 1):
                comment_parts.append(f"{i}. {update}")
            
            comment_parts.append(f"\n*Updated: {datetime.now().strftime('%H:%M UTC')}*")
            
            comment_body = '\n'.join(comment_parts)
            await self.create_comment(repo_full_name, issue_number, comment_body)
            
            logger.info(
                "Progress thread created",
                repo=repo_full_name,
                issue=issue_number,
                updates_count=len(updates)
            )

        except Exception as e:
            logger.error(
                "Failed to create progress thread",
                error=str(e),
                repo=repo_full_name,
                issue=issue_number
            )

    async def request_specific_feedback(self, repo_full_name: str, issue_number: int,
                                      question: str, options: List[str] = None,
                                      timeout_hours: int = 24) -> None:
        """Request specific feedback with options and timeout"""
        try:
            # Transition to awaiting feedback state
            await self.transition_agent_state(
                repo_full_name, issue_number, 
                None, "agent:awaiting-feedback",
                f"Requesting feedback: {question}"
            )

            # Build feedback request comment
            comment_parts = [
                "❓ **Feedback Requested**",
                f"\n{question}"
            ]

            if options:
                comment_parts.append("\n**Please choose one of the following options:**")
                for i, option in enumerate(options, 1):
                    comment_parts.append(f"{i}. {option}")
                comment_parts.append("\n*Reply with the number or the full text of your choice.*")

            comment_parts.extend([
                "\n**Available commands:**",
                "- `/cancel` - Cancel this task",
                "- `/retry` - Retry from the beginning", 
                "- `/escalate` - Escalate to human review",
                f"\n*This request will timeout in {timeout_hours} hours if no response is received.*"
            ])

            comment_body = '\n'.join(comment_parts)
            await self.create_comment(repo_full_name, issue_number, comment_body)

            logger.info(
                "Feedback request created",
                repo=repo_full_name,
                issue=issue_number,
                timeout_hours=timeout_hours
            )

        except Exception as e:
            logger.error(
                "Failed to request feedback",
                error=str(e),
                repo=repo_full_name,
                issue=issue_number
            )

    async def create_validation_feedback(self, repo_full_name: str, issue_number: int,
                                       validation_result: Dict[str, Any]) -> None:
        """Create validation feedback comment"""
        try:
            if validation_result['is_valid']:
                emoji = "✅"
                title = "Task Validation Successful"
                message = f"Your task has been validated with a completeness score of {validation_result['completeness_score']}/100."
            else:
                emoji = "⚠️"
                title = "Task Validation Issues Found"
                message = "Please address the following issues to improve your task:"

            comment_parts = [f"{emoji} **{title}**", f"\n{message}"]

            if validation_result.get('errors'):
                comment_parts.append("\n**❌ Issues to Fix:**")
                for error in validation_result['errors']:
                    comment_parts.append(f"- {error}")

            if validation_result.get('warnings'):
                comment_parts.append("\n**⚠️ Warnings:**")
                for warning in validation_result['warnings']:
                    comment_parts.append(f"- {warning}")

            if validation_result.get('suggestions'):
                comment_parts.append("\n**💡 Suggestions:**")
                for suggestion in validation_result['suggestions']:
                    comment_parts.append(f"- {suggestion}")

            if not validation_result['is_valid']:
                comment_parts.extend([
                    "\n**What to do next:**",
                    "1. Edit your issue description to address the issues above",
                    "2. Comment `/retry` to re-validate your task",
                    "3. Or comment `/escalate` if you need human assistance"
                ])

            comment_body = '\n'.join(comment_parts)
            await self.create_comment(repo_full_name, issue_number, comment_body)

        except Exception as e:
            logger.error("Failed to create validation feedback", error=str(e))

    async def create_escalation_comment(self, repo_full_name: str, issue_number: int,
                                      escalation_reason: str, context: Dict[str, Any] = None) -> None:
        """Create escalation comment for human review"""
        try:
            comment_parts = [
                "🚨 **Task Escalated for Human Review**",
                f"\n**Reason**: {escalation_reason}",
                f"\n**Time**: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}"
            ]

            if context:
                if context.get('error_count'):
                    comment_parts.append(f"**Error Count**: {context['error_count']}")
                if context.get('retry_count'):
                    comment_parts.append(f"**Retry Count**: {context['retry_count']}")
                if context.get('last_error'):
                    comment_parts.append(f"**Last Error**: {context['last_error']}")

            comment_parts.extend([
                "\n**Next Steps:**",
                "- A human reviewer will examine this task",
                "- You may receive additional questions or requests for clarification",
                "- The task may be reassigned or modified based on the review",
                "\n*This issue will remain open pending human review.*"
            ])

            comment_body = '\n'.join(comment_parts)
            await self.create_comment(repo_full_name, issue_number, comment_body)

            # Also add escalated label
            await self.add_label(repo_full_name, issue_number, "agent:escalated")

        except Exception as e:
            logger.error("Failed to create escalation comment", error=str(e))

    async def create_cancellation_comment(self, repo_full_name: str, issue_number: int,
                                        cancellation_reason: str = "User request") -> None:
        """Create cancellation comment"""
        try:
            comment_body = f"🚫 **Task Cancelled**\n\n**Reason**: {cancellation_reason}\n\n*This task can be restarted by adding the `agent:queued` label.*"
            await self.create_comment(repo_full_name, issue_number, comment_body)
            await self.add_label(repo_full_name, issue_number, "agent:cancelled")

        except Exception as e:
            logger.error("Failed to create cancellation comment", error=str(e))

    async def get_issue_labels(self, repo_full_name: str, issue_number: int) -> List[str]:
        """Get current labels for an issue"""
        try:
            issue_data = await self.get_issue(repo_full_name, issue_number)
            return [label['name'] for label in issue_data.get('labels', [])]
        except Exception as e:
            logger.error("Failed to get issue labels", error=str(e))
            return []

    async def get_latest_comments(self, repo_full_name: str, issue_number: int, 
                                limit: int = 10) -> List[Dict[str, Any]]:
        """Get the latest comments for an issue"""
        try:
            comments = await self.get_comments(repo_full_name, issue_number)
            # Return the most recent comments (GitHub returns in chronological order)
            return comments[-limit:] if len(comments) > limit else comments
        except Exception as e:
            logger.error("Failed to get latest comments", error=str(e))
            return []

    async def has_agent_label(self, repo_full_name: str, issue_number: int) -> bool:
        """Check if issue has any agent-related label"""
        try:
            labels = await self.get_issue_labels(repo_full_name, issue_number)
            return any(label.startswith('agent:') for label in labels)
        except Exception as e:
            logger.error("Failed to check agent labels", error=str(e))
            return False

    async def get_current_agent_state(self, repo_full_name: str, issue_number: int) -> Optional[str]:
        """Get current agent state from labels"""
        try:
            labels = await self.get_issue_labels(repo_full_name, issue_number)
            agent_labels = [label for label in labels if label.startswith('agent:')]
            return agent_labels[0] if agent_labels else None
        except Exception as e:
            logger.error("Failed to get current agent state", error=str(e))
            return None