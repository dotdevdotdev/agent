"""
Rich progress reporting and user communication
"""

import structlog
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass

from .github_client import GitHubClient
from .agent_state_machine import AgentState, StateContext

logger = structlog.get_logger()


@dataclass
class ProgressReport:
    job_id: str
    current_state: AgentState
    progress_percentage: int
    message: str
    technical_details: Optional[str] = None
    estimated_completion: Optional[datetime] = None
    time_elapsed: Optional[timedelta] = None
    steps_completed: List[str] = None
    next_steps: List[str] = None
    can_cancel: bool = True
    can_retry: bool = False


class ProgressReporter:
    """Generates rich progress reports and user communications"""

    def __init__(self, github_client: GitHubClient):
        self.github_client = github_client
        self.progress_templates = self._initialize_progress_templates()
        self.emoji_map = self._initialize_emoji_map()

    async def create_progress_comment(self, repo_full_name: str, issue_number: int,
                                    state: AgentState, progress: int, message: str,
                                    technical_details: str = None, 
                                    estimated_completion: datetime = None,
                                    steps_completed: List[str] = None,
                                    next_steps: List[str] = None) -> None:
        """Create detailed progress comment"""
        try:
            # Build progress comment
            comment_body = self._build_progress_comment(
                state, progress, message, technical_details, 
                estimated_completion, steps_completed, next_steps
            )

            await self.github_client.create_comment(repo_full_name, issue_number, comment_body)
            
            logger.info(
                "Progress comment created",
                repo=repo_full_name,
                issue=issue_number,
                state=state.value,
                progress=progress
            )

        except Exception as e:
            logger.error(
                "Failed to create progress comment",
                error=str(e),
                repo=repo_full_name,
                issue=issue_number
            )

    async def create_status_summary(self, job_id: str, context: StateContext,
                                  additional_info: Dict[str, Any] = None) -> str:
        """Generate comprehensive status summary"""
        time_elapsed = datetime.now() - context.state_entered_at
        
        # Calculate estimated completion based on current progress and historical data
        estimated_completion = self._estimate_completion_time(context, additional_info)
        
        summary_parts = [
            f"## 🤖 Agent Status Summary",
            f"**Job ID**: `{job_id}`",
            f"**Current State**: {self._format_state_with_emoji(context.current_state)}",
            f"**Time Elapsed**: {self._format_duration(time_elapsed)}",
        ]

        if estimated_completion:
            summary_parts.append(f"**Estimated Completion**: {estimated_completion.strftime('%H:%M UTC')}")

        # Add progress bar
        progress = self._get_progress_for_state(context.current_state)
        progress_bar = self._create_progress_bar(progress)
        summary_parts.append(f"**Progress**: {progress_bar} {progress}%")

        # Add recent activities
        if context.metadata.get('recent_activities'):
            summary_parts.append("\n### Recent Activities")
            for activity in context.metadata['recent_activities'][-3:]:  # Last 3 activities
                summary_parts.append(f"- {activity}")

        # Add next steps
        next_steps = self._get_next_steps_for_state(context.current_state)
        if next_steps:
            summary_parts.append("\n### Next Steps")
            for step in next_steps:
                summary_parts.append(f"- {step}")

        # Add error information if any
        if context.error_count > 0:
            summary_parts.append(f"\n⚠️ **Errors Encountered**: {context.error_count}")
            if context.metadata.get('last_error'):
                error_info = context.metadata['last_error']
                summary_parts.append(f"Last error: {error_info.get('error', 'Unknown error')}")

        return '\n'.join(summary_parts)

    async def update_issue_title_with_progress(self, repo_full_name: str, issue_number: int,
                                             original_title: str, state: AgentState, 
                                             progress: int) -> None:
        """Update issue title to include progress indicator"""
        try:
            # Create title with progress indicator
            state_emoji = self.emoji_map.get(state, "🤖")
            progress_indicator = f"[{progress}%]" if progress > 0 else ""
            
            new_title = f"{state_emoji} {progress_indicator} {original_title}".strip()
            
            # Only update if title has changed significantly
            if len(new_title) <= 255:  # GitHub title limit
                await self.github_client.update_issue(
                    repo_full_name, issue_number, title=new_title
                )
                logger.info("Issue title updated with progress", issue=issue_number, progress=progress)

        except Exception as e:
            logger.error("Failed to update issue title", error=str(e), issue=issue_number)

    async def create_completion_report(self, repo_full_name: str, issue_number: int,
                                     job_id: str, results: Dict[str, Any],
                                     time_elapsed: timedelta) -> None:
        """Create comprehensive completion report"""
        try:
            report_parts = [
                "## ✅ Task Completed Successfully!",
                f"**Job ID**: `{job_id}`",
                f"**Total Time**: {self._format_duration(time_elapsed)}",
                f"**Completion Time**: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}",
            ]

            # Add results summary
            if results.get('summary'):
                report_parts.extend([
                    "\n### Summary",
                    results['summary']
                ])

            # Add files modified
            if results.get('files_modified'):
                report_parts.append("\n### Files Modified")
                for file_path in results['files_modified']:
                    report_parts.append(f"- `{file_path}`")

            # Add output/artifacts
            if results.get('output'):
                report_parts.extend([
                    "\n### Output",
                    f"```\n{results['output']}\n```"
                ])

            # Add performance metrics
            if results.get('performance_metrics'):
                metrics = results['performance_metrics']
                report_parts.append("\n### Performance Metrics")
                for metric, value in metrics.items():
                    report_parts.append(f"- **{metric}**: {value}")

            # Add next steps or recommendations
            if results.get('recommendations'):
                report_parts.append("\n### Recommendations")
                for rec in results['recommendations']:
                    report_parts.append(f"- {rec}")

            report_parts.append("\n---\n*This task was completed by the AI agent. Please review the results and feel free to ask questions or request modifications.*")

            comment_body = '\n'.join(report_parts)
            await self.github_client.create_comment(repo_full_name, issue_number, comment_body)

            logger.info("Completion report created", job_id=job_id, issue=issue_number)

        except Exception as e:
            logger.error("Failed to create completion report", error=str(e), job_id=job_id)

    async def create_error_report(self, repo_full_name: str, issue_number: int,
                                job_id: str, error: Exception, 
                                recovery_options: List[str] = None) -> None:
        """Create detailed error report with recovery options"""
        try:
            report_parts = [
                "## ❌ Task Failed",
                f"**Job ID**: `{job_id}`",
                f"**Error Time**: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}",
                f"**Error Type**: `{type(error).__name__}`",
            ]

            # Add error details
            report_parts.extend([
                "\n### Error Details",
                f"```\n{str(error)}\n```"
            ])

            # Add recovery options
            if recovery_options:
                report_parts.append("\n### Recovery Options")
                for i, option in enumerate(recovery_options, 1):
                    report_parts.append(f"{i}. {option}")
            else:
                report_parts.extend([
                    "\n### What You Can Do",
                    "- Comment `/retry` to retry the task from the beginning",
                    "- Comment `/escalate` to escalate to human review",
                    "- Modify your original request and create a new issue",
                    "- Ask questions about the error for clarification"
                ])

            report_parts.append("\n---\n*The agent encountered an error while processing your task. Please use one of the recovery options above or create a new issue with more details.*")

            comment_body = '\n'.join(report_parts)
            await self.github_client.create_comment(repo_full_name, issue_number, comment_body)

            logger.info("Error report created", job_id=job_id, issue=issue_number)

        except Exception as e:
            logger.error("Failed to create error report", error=str(e), job_id=job_id)

    def _build_progress_comment(self, state: AgentState, progress: int, message: str,
                              technical_details: str = None, 
                              estimated_completion: datetime = None,
                              steps_completed: List[str] = None,
                              next_steps: List[str] = None) -> str:
        """Build formatted progress comment"""
        emoji = self.emoji_map.get(state, "🤖")
        progress_bar = self._create_progress_bar(progress)
        
        comment_parts = [
            f"## {emoji} Progress Update",
            f"**Status**: {state.value}",
            f"**Progress**: {progress_bar} {progress}%",
            f"**Update**: {message}"
        ]

        if estimated_completion:
            comment_parts.append(f"**Estimated Completion**: {estimated_completion.strftime('%H:%M UTC')}")

        if steps_completed:
            comment_parts.append("\n### ✅ Completed Steps")
            for step in steps_completed:
                comment_parts.append(f"- {step}")

        if next_steps:
            comment_parts.append("\n### 🔄 Next Steps")
            for step in next_steps:
                comment_parts.append(f"- {step}")

        if technical_details:
            comment_parts.extend([
                "\n<details><summary>🔧 Technical Details</summary>",
                "",
                technical_details,
                "</details>"
            ])

        comment_parts.append(f"\n*Last updated: {datetime.now().strftime('%H:%M UTC')}*")

        return '\n'.join(comment_parts)

    def _create_progress_bar(self, progress: int, width: int = 20) -> str:
        """Create ASCII progress bar"""
        filled = int(width * progress / 100)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}]"

    def _format_state_with_emoji(self, state: AgentState) -> str:
        """Format state with appropriate emoji"""
        emoji = self.emoji_map.get(state, "🤖")
        return f"{emoji} {state.value}"

    def _format_duration(self, duration: timedelta) -> str:
        """Format duration in human-readable format"""
        total_seconds = int(duration.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"

    def _estimate_completion_time(self, context: StateContext, 
                                additional_info: Dict[str, Any] = None) -> Optional[datetime]:
        """Estimate completion time based on current progress and historical data"""
        current_progress = self._get_progress_for_state(context.current_state)
        
        if current_progress >= 100:
            return None  # Already complete
        
        # Simple estimation based on elapsed time and progress
        time_elapsed = datetime.now() - context.state_entered_at
        if current_progress > 0:
            estimated_total_time = time_elapsed * (100 / current_progress)
            remaining_time = estimated_total_time - time_elapsed
            return datetime.now() + remaining_time
        
        return None

    def _get_progress_for_state(self, state: AgentState) -> int:
        """Get progress percentage for current state"""
        progress_map = {
            AgentState.QUEUED: 0,
            AgentState.VALIDATING: 5,
            AgentState.ANALYZING: 15,
            AgentState.IN_PROGRESS: 30,
            AgentState.IMPLEMENTING: 60,
            AgentState.TESTING: 80,
            AgentState.AWAITING_FEEDBACK: 50,
            AgentState.COMPLETED: 100,
            AgentState.FAILED: 0,
            AgentState.CANCELLED: 0,
            AgentState.ESCALATED: 0
        }
        return progress_map.get(state, 0)

    def _get_next_steps_for_state(self, state: AgentState) -> List[str]:
        """Get next steps for current state"""
        next_steps_map = {
            AgentState.QUEUED: ["Validate task requirements", "Begin analysis"],
            AgentState.VALIDATING: ["Check task completeness", "Start processing if valid"],
            AgentState.ANALYZING: ["Understand requirements", "Plan implementation approach"],
            AgentState.IN_PROGRESS: ["Execute the planned approach", "Monitor progress"],
            AgentState.IMPLEMENTING: ["Apply changes", "Test implementation"],
            AgentState.TESTING: ["Validate results", "Prepare final output"],
            AgentState.AWAITING_FEEDBACK: ["Wait for user response", "Process feedback once received"],
            AgentState.COMPLETED: ["Review results", "Close issue"],
            AgentState.FAILED: ["Analyze error", "Determine recovery options"],
            AgentState.CANCELLED: ["Task cancelled by user"],
            AgentState.ESCALATED: ["Waiting for human review"]
        }
        return next_steps_map.get(state, [])

    def _initialize_progress_templates(self) -> Dict[AgentState, str]:
        """Initialize progress message templates"""
        return {
            AgentState.QUEUED: "Your task has been queued and will be processed shortly.",
            AgentState.VALIDATING: "Validating your task requirements and checking for completeness.",
            AgentState.ANALYZING: "Analyzing your request and planning the approach.",
            AgentState.IN_PROGRESS: "Working on your task. This may take a while for complex requests.",
            AgentState.IMPLEMENTING: "Implementing the solution based on the analysis.",
            AgentState.TESTING: "Testing the implementation and validating results.",
            AgentState.AWAITING_FEEDBACK: "Waiting for your feedback to continue processing.",
            AgentState.COMPLETED: "Task completed successfully! Results are available above.",
            AgentState.FAILED: "Task failed to complete. Please check the error details.",
            AgentState.CANCELLED: "Task was cancelled by user request.",
            AgentState.ESCALATED: "Task has been escalated for human review."
        }

    def _initialize_emoji_map(self) -> Dict[AgentState, str]:
        """Initialize emoji mapping for states"""
        return {
            AgentState.QUEUED: "⏳",
            AgentState.VALIDATING: "🔍",
            AgentState.ANALYZING: "🧠",
            AgentState.IN_PROGRESS: "⚙️",
            AgentState.IMPLEMENTING: "🛠️",
            AgentState.TESTING: "🧪",
            AgentState.AWAITING_FEEDBACK: "❓",
            AgentState.COMPLETED: "✅",
            AgentState.FAILED: "❌",
            AgentState.CANCELLED: "🚫",
            AgentState.ESCALATED: "🚨"
        }