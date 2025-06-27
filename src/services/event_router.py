"""
Intelligent GitHub event routing and processing
"""

import asyncio
import structlog
from typing import Dict, List, Callable, Any, Optional
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

from .github_client import GitHubClient
from .job_manager import JobManager
from .agent_state_machine import AgentStateMachine, AgentState
from .issue_parser import IssueParser
from .task_validator import TaskValidator
from .processing_orchestrator import ProcessingOrchestrator
from .worktree_manager import WorktreeStatus
from .issue_parser import TaskType, OutputFormat as IssueOutputFormat

logger = structlog.get_logger()


class EventProcessor(ABC):
    """Abstract base class for event processors"""

    def __init__(self, github_client: GitHubClient, job_manager: JobManager, 
                 state_machine: AgentStateMachine):
        self.github_client = github_client
        self.job_manager = job_manager
        self.state_machine = state_machine

    @abstractmethod
    async def can_handle(self, event_type: str, payload: Dict[str, Any]) -> bool:
        """Check if this processor can handle the event"""
        pass

    @abstractmethod
    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process the event and return result"""
        pass


class IssueEventProcessor(EventProcessor):
    """Processes GitHub issue events"""

    def __init__(self, github_client: GitHubClient, job_manager: JobManager, 
                 state_machine: AgentStateMachine):
        super().__init__(github_client, job_manager, state_machine)
        self.issue_parser = IssueParser()
        self.task_validator = TaskValidator()
        self.processing_orchestrator = ProcessingOrchestrator(
            github_client=github_client,
            state_machine=state_machine
        )

    async def can_handle(self, event_type: str, payload: Dict[str, Any]) -> bool:
        return event_type == "issues"

    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        action = payload.get('action')
        issue = payload.get('issue', {})
        repository = payload.get('repository', {})

        repo_full_name = repository.get('full_name')
        issue_number = issue.get('number')

        logger.info(
            "Processing issue event",
            action=action,
            repo=repo_full_name,
            issue=issue_number
        )

        if action == 'opened':
            return await self._handle_issue_opened(payload)
        elif action == 'labeled':
            return await self._handle_issue_labeled(payload)
        elif action == 'unlabeled':
            return await self._handle_issue_unlabeled(payload)
        elif action == 'edited':
            return await self._handle_issue_edited(payload)
        elif action == 'closed':
            return await self._handle_issue_closed(payload)
        elif action == 'reopened':
            return await self._handle_issue_reopened(payload)
        else:
            return {"status": "ignored", "reason": f"Unsupported action: {action}"}

    async def _handle_issue_opened(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle new issue creation"""
        issue = payload['issue']
        repository = payload['repository']
        
        repo_full_name = repository['full_name']
        issue_number = issue['number']
        issue_title = issue['title']
        issue_body = issue.get('body', '')
        issue_labels = [label['name'] for label in issue.get('labels', [])]

        # Check if this is an agent task
        is_agent_task = (
            self.issue_parser.is_agent_issue(issue_body, issue_labels) or
            'agent:queued' in issue_labels
        )

        if not is_agent_task:
            return {"status": "ignored", "reason": "Not an agent task"}

        # Check if a job already exists for this issue to prevent duplicates
        existing_jobs = await self.job_manager.list_jobs()
        for existing_job in existing_jobs:
            if (existing_job.repository_full_name == repo_full_name and 
                existing_job.issue_number == issue_number and
                existing_job.status in ['pending', 'running']):
                logger.info(
                    "Job already exists for this issue",
                    job_id=existing_job.job_id,
                    issue=issue_number,
                    status=existing_job.status
                )
                return {
                    "status": "duplicate_job_prevented",
                    "job_id": existing_job.job_id,
                    "message": "Job already exists for this issue"
                }

        try:
            # Parse the issue
            issue_author = issue.get('user', {}).get('login', '')
            parsed_task = self.issue_parser.parse_issue(issue_body, issue_title, issue_author)
            
            # Validate the task
            validation_result = self.task_validator.validate_task_completeness(parsed_task)

            # Create job
            from src.models.jobs import JobCreate
            job_create = JobCreate(
                issue_number=issue_number,
                repository_full_name=repo_full_name,
                issue_title=issue_title,
                issue_body=issue_body,
                metadata={
                    'parsed_task': parsed_task.__dict__,
                    'validation_result': validation_result
                }
            )

            job = await self.job_manager.create_job(job_create)

            # Initialize state machine context
            context = await self.state_machine.initialize_context(
                job.job_id, repo_full_name, issue_number
            )

            # Check if task is ready for processing (respects testing mode)
            if not self.task_validator.is_ready_for_processing(parsed_task):
                await self.github_client.create_validation_feedback(
                    repo_full_name, issue_number, validation_result
                )
                await self.state_machine.transition_to(
                    job.job_id, AgentState.AWAITING_FEEDBACK,
                    {'validation_failed': True}
                )
                return {
                    "status": "validation_failed",
                    "job_id": job.job_id,
                    "message": "Task validation failed, feedback requested"
                }

            # Start processing
            await self.state_machine.transition_to(
                job.job_id, AgentState.VALIDATING,
                user_message="Task validation successful, beginning processing..."
            )

            # Schedule the actual processing
            asyncio.create_task(self._process_validated_task(job.job_id, parsed_task))

            return {
                "status": "accepted",
                "job_id": job.job_id,
                "message": "Task accepted and processing started"
            }

        except Exception as e:
            logger.error("Failed to process new issue", error=str(e), issue=issue_number)
            return {"status": "error", "error": str(e)}

    async def _handle_issue_labeled(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle issue labeling"""
        issue = payload['issue']
        label = payload.get('label', {})
        
        repo_full_name = payload['repository']['full_name']
        issue_number = issue['number']
        label_name = label.get('name', '')

        # Check for agent:queued label (restart/retry)
        if label_name == 'agent:queued':
            # Check if there's an existing job
            existing_jobs = await self.job_manager.list_jobs()
            existing_job = None
            for job in existing_jobs:
                if (job.repository_full_name == repo_full_name and 
                    job.issue_number == issue_number):
                    existing_job = job
                    break

            if existing_job and existing_job.status in ['failed', 'cancelled']:
                # Restart the job
                await self._restart_job(existing_job.job_id)
                return {"status": "restarted", "job_id": existing_job.job_id}

        return {"status": "ignored", "reason": f"Label {label_name} does not trigger action"}

    async def _handle_issue_unlabeled(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle issue label removal"""
        # For now, we don't take action on label removal
        return {"status": "ignored", "reason": "Label removal events not processed"}

    async def _handle_issue_edited(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle issue editing"""
        issue = payload['issue']
        changes = payload.get('changes', {})
        
        # If the issue body was changed and it's an active agent task, 
        # we might want to re-validate
        if 'body' in changes:
            repo_full_name = payload['repository']['full_name']
            issue_number = issue['number']
            
            # Check if there's an active agent task
            current_state = await self.github_client.get_current_agent_state(
                repo_full_name, issue_number
            )
            
            if current_state and current_state in ['agent:awaiting-feedback', 'agent:failed']:
                # Issue was edited while awaiting feedback - might be worth re-validating
                await self.github_client.create_comment(
                    repo_full_name, issue_number,
                    "📝 **Issue Updated**\n\nI noticed you edited the issue. " +
                    "Comment `/retry` if you'd like me to re-process with the new information."
                )

        return {"status": "acknowledged", "message": "Issue edit noted"}

    async def _handle_issue_closed(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle issue closure"""
        issue = payload['issue']
        repo_full_name = payload['repository']['full_name']
        issue_number = issue['number']

        # Find and cancel any active jobs for this issue
        jobs = await self.job_manager.list_jobs(status=None)
        for job in jobs:
            if (job.repository_full_name == repo_full_name and 
                job.issue_number == issue_number and
                job.status in ['pending', 'running']):
                
                await self.job_manager.cancel_job(job.job_id)
                await self.state_machine.transition_to(
                    job.job_id, AgentState.CANCELLED,
                    user_message="Task cancelled due to issue closure"
                )
                logger.info("Job cancelled due to issue closure", job_id=job.job_id)

        return {"status": "handled", "message": "Active jobs cancelled"}

    async def _handle_issue_reopened(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle issue reopening"""
        # For now, just acknowledge. User can add agent:queued label to restart
        return {"status": "acknowledged", "message": "Issue reopened, add agent:queued to restart processing"}

    async def _process_validated_task(self, job_id: str, parsed_task) -> None:
        """Process a validated task using the complete Claude Code CLI workflow"""
        try:
            # Get job details from job manager
            job = await self.job_manager.get_job(job_id)
            if not job:
                raise Exception(f"Job {job_id} not found")
            
            # Create progress callback to update job status
            async def progress_callback(message: str, progress: int):
                await self.job_manager.update_job_progress(job_id, progress, message)
                logger.info("Processing progress", job_id=job_id, progress=progress, message=message)
                
                # Save worktree info during processing for recovery
                if hasattr(self.processing_orchestrator, 'active_contexts') and job_id in self.processing_orchestrator.active_contexts:
                    context = self.processing_orchestrator.active_contexts[job_id]
                    if context.session and context.session.worktree_info:
                        worktree_info = self._extract_worktree_info(context)
                        if worktree_info:
                            # Update job metadata with current worktree info
                            job = await self.job_manager.get_job(job_id)
                            if job and job.metadata:
                                job.metadata["current_worktree_info"] = worktree_info
            
            # Check if user is admin to determine processing type
            from config.settings import settings
            is_admin = settings.is_admin_user(parsed_task.issue_author)
            
            # Choose processing method based on admin status and task type
            is_general_question = (
                parsed_task.task_type == TaskType.QUESTION or 
                parsed_task.output_format == IssueOutputFormat.GENERAL_RESPONSE
            )
            
            # Non-admin users get simple responses regardless of task type
            if not is_admin:
                logger.info("Non-admin user detected, providing simple response", job_id=job_id, user=parsed_task.issue_author)
                await self._provide_simple_response(job_id, job.repository_full_name, job.issue_number, parsed_task)
                return
            
            # Admin users get full processing
            if is_general_question:
                # Use simplified workflow for general questions
                logger.info("Using simplified workflow for general question", job_id=job_id)
                result_context = await self.processing_orchestrator.process_general_question(
                    job_id=job_id,
                    repository=job.repository_full_name,
                    issue_number=job.issue_number,
                    parsed_task=parsed_task,
                    progress_callback=progress_callback
                )
            else:
                # Use full workflow for code-related tasks
                logger.info("Using full workflow for code-related task", job_id=job_id)
                result_context = await self.processing_orchestrator.process_issue(
                    job_id=job_id,
                    repository=job.repository_full_name,
                    issue_number=job.issue_number,
                    parsed_task=parsed_task,
                    progress_callback=progress_callback
                )
            
            # Update job with final results including worktree information
            final_result = {
                "message": "Task processed successfully using Claude Code CLI",
                "result_type": result_context.parsed_result.result_type.value if result_context.parsed_result else "unknown",
                "confidence_score": result_context.parsed_result.confidence_score if result_context.parsed_result else 0,
                "code_changes_count": len(result_context.parsed_result.code_changes) if result_context.parsed_result else 0,
                "recommendations_count": len(result_context.parsed_result.recommendations) if result_context.parsed_result else 0,
                "processing_metadata": result_context.metadata,
                "worktree_info": self._extract_worktree_info(result_context) if result_context.session else None
            }
            
            await self.job_manager.update_job_status(
                job_id, "completed",
                result=final_result
            )
            
            logger.info(
                "Task processing completed successfully",
                job_id=job_id,
                result_type=result_context.parsed_result.result_type.value if result_context.parsed_result else "unknown",
                duration=result_context.metadata.get("total_duration", 0)
            )

        except Exception as e:
            # Handle errors through state machine
            if hasattr(self, 'state_machine') and self.state_machine:
                await self.state_machine.handle_error(job_id, e)
            
            # Update job status
            await self.job_manager.update_job_status(
                job_id, "failed", 
                error_message=str(e)
            )
            
            logger.error("Task processing failed", job_id=job_id, error=str(e))

    async def _restart_job(self, job_id: str) -> None:
        """Restart a failed or cancelled job"""
        try:
            await self.job_manager.update_job_status(job_id, "running")
            await self.state_machine.transition_to(
                job_id, AgentState.QUEUED,
                user_message="Task restarted and queued for processing..."
            )
            logger.info("Job restarted", job_id=job_id)
        except Exception as e:
            logger.error("Failed to restart job", job_id=job_id, error=str(e))

    async def _provide_simple_response(self, job_id: str, repository: str, issue_number: int, parsed_task) -> None:
        """Provide a simple acknowledgment response for non-admin users"""
        try:
            # Update state to in progress
            await self.state_machine.transition_to(
                job_id, AgentState.IN_PROGRESS,
                user_message="Processing your request..."
            )
            
            # Create simple acknowledgment message
            simple_response = f"""## Thank you for your request!

We've received your {parsed_task.task_type.value.lower()} request and will respond soon.

**Your request:** {parsed_task.prompt[:200]}{'...' if len(parsed_task.prompt) > 200 else ''}

Our team will review this and provide a response. For immediate assistance with urgent issues, please contact repository maintainers directly.

---
*This is an automated acknowledgment. A human will review and respond to your request.*"""

            # Post the simple response
            await self.github_client.create_comment(repository, issue_number, simple_response)
            
            # Update labels
            await self.github_client.add_labels(repository, issue_number, ["agent:completed"])
            try:
                await self.github_client.remove_label(repository, issue_number, "agent:in-progress")
                await self.github_client.remove_label(repository, issue_number, "agent:queued")
            except:
                pass  # Labels might not exist
            
            # Complete the job
            await self.state_machine.transition_to(
                job_id, AgentState.COMPLETED,
                user_message="Simple acknowledgment provided"
            )
            
            await self.job_manager.mark_job_completed(job_id, {"simple_response": True})
            
            logger.info("Simple response provided", job_id=job_id, user=parsed_task.issue_author)
            
        except Exception as e:
            logger.error("Failed to provide simple response", job_id=job_id, error=str(e))
            await self.state_machine.transition_to(
                job_id, AgentState.FAILED,
                user_message=f"Failed to provide response: {str(e)}"
            )

    def _extract_worktree_info(self, result_context) -> Dict[str, Any]:
        """Extract worktree information for job recovery"""
        if not result_context.session or not result_context.session.worktree_info:
            return None
        
        worktree_info = result_context.session.worktree_info
        session = result_context.session
        
        return {
            "job_id": session.job_id,
            "worktree_path": str(worktree_info.worktree_path),
            "branch_name": worktree_info.branch_name,
            "base_commit": worktree_info.base_commit,
            "status": session.status.value,
            "created_at": session.created_at.isoformat(),
            "files_modified": session.files_modified,
            "files_created": session.files_created,
            "commits_made": session.commits_made,
            "can_recover": session.status in [WorktreeStatus.READY, WorktreeStatus.PROCESSING, WorktreeStatus.COMPLETED]
        }


class CommentEventProcessor(EventProcessor):
    """Processes GitHub comment events"""

    async def can_handle(self, event_type: str, payload: Dict[str, Any]) -> bool:
        return event_type == "issue_comment"

    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        action = payload.get('action')
        
        if action == 'created':
            return await self._handle_comment_created(payload)
        elif action == 'edited':
            return await self._handle_comment_edited(payload)
        else:
            return {"status": "ignored", "reason": f"Unsupported action: {action}"}

    async def _handle_comment_created(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle new comment creation"""
        comment = payload['comment']
        issue = payload['issue']
        repository = payload['repository']
        
        repo_full_name = repository['full_name']
        issue_number = issue['number']
        comment_body = comment['body']
        commenter = comment['user']['login']

        # Skip bot comments
        if comment['user']['type'] == 'Bot':
            return {"status": "ignored", "reason": "Bot comment"}

        # Check if this issue has an active agent task
        current_state = await self.github_client.get_current_agent_state(
            repo_full_name, issue_number
        )

        if not current_state:
            return {"status": "ignored", "reason": "No active agent task"}

        # Find the job for this issue
        jobs = await self.job_manager.list_jobs()
        job = None
        for j in jobs:
            if (j.repository_full_name == repo_full_name and 
                j.issue_number == issue_number and
                j.status in ['pending', 'running']):
                job = j
                break

        if not job:
            return {"status": "ignored", "reason": "No active job found"}

        # Process the comment
        await self.state_machine.handle_user_response(
            job.job_id, comment_body, commenter
        )

        return {"status": "processed", "job_id": job.job_id}

    async def _handle_comment_edited(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle comment editing"""
        # For now, we don't process comment edits differently
        return {"status": "ignored", "reason": "Comment edits not processed"}


class LabelEventProcessor(EventProcessor):
    """Processes GitHub label events (part of issue events)"""

    async def can_handle(self, event_type: str, payload: Dict[str, Any]) -> bool:
        # Label events are actually part of issue events
        return False

    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "ignored"}


class PullRequestEventProcessor(EventProcessor):
    """Processes GitHub pull request events (future extension)"""

    async def can_handle(self, event_type: str, payload: Dict[str, Any]) -> bool:
        return event_type == "pull_request"

    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Future: Process PR events for agent-created PRs
        return {"status": "ignored", "reason": "PR events not yet implemented"}


class EventRouter:
    """Routes GitHub events to appropriate processors"""

    def __init__(self, github_client: GitHubClient, job_manager: JobManager, 
                 state_machine: AgentStateMachine):
        self.github_client = github_client
        self.job_manager = job_manager
        self.state_machine = state_machine
        
        # Initialize processors
        self.processors: List[EventProcessor] = [
            IssueEventProcessor(github_client, job_manager, state_machine),
            CommentEventProcessor(github_client, job_manager, state_machine),
            LabelEventProcessor(github_client, job_manager, state_machine),
            PullRequestEventProcessor(github_client, job_manager, state_machine)
        ]
        
        # Event filtering and rate limiting
        self.event_cache: Dict[str, datetime] = {}
        self.rate_limit_window = timedelta(seconds=30)

    async def route_event(self, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Route event to appropriate processor"""
        
        # Generate event fingerprint for deduplication
        event_fingerprint = self._generate_event_fingerprint(event_type, payload)
        
        # Check for duplicate events (GitHub sometimes sends duplicates)
        if self._is_duplicate_event(event_fingerprint):
            logger.info("Duplicate event detected, skipping", fingerprint=event_fingerprint)
            return {"status": "duplicate", "message": "Event already processed"}

        # Update event cache
        self.event_cache[event_fingerprint] = datetime.now()

        # Find appropriate processor
        for processor in self.processors:
            if await processor.can_handle(event_type, payload):
                try:
                    result = await processor.process(payload)
                    
                    logger.info(
                        "Event processed",
                        event_type=event_type,
                        processor=processor.__class__.__name__,
                        status=result.get('status')
                    )
                    
                    return result
                    
                except Exception as e:
                    logger.error(
                        "Event processing failed",
                        event_type=event_type,
                        processor=processor.__class__.__name__,
                        error=str(e)
                    )
                    return {"status": "error", "error": str(e)}

        # No processor found
        return {"status": "unhandled", "message": f"No processor for event type: {event_type}"}

    def _generate_event_fingerprint(self, event_type: str, payload: Dict[str, Any]) -> str:
        """Generate unique fingerprint for event deduplication"""
        
        # Extract key identifiers based on event type
        if event_type == "issues":
            issue_id = payload.get('issue', {}).get('id')
            action = payload.get('action')
            repo_id = payload.get('repository', {}).get('id')
            
            # For issue events that might create jobs, use issue-based fingerprint
            # to prevent multiple job creation attempts for the same issue
            if action in ['opened', 'labeled', 'reopened']:
                return f"issue_job_creation:{repo_id}:{issue_id}"
            else:
                return f"{event_type}:{action}:{issue_id}"
            
        elif event_type == "issue_comment":
            comment_id = payload.get('comment', {}).get('id')
            action = payload.get('action')
            return f"{event_type}:{action}:{comment_id}"
            
        elif event_type == "pull_request":
            pr_id = payload.get('pull_request', {}).get('id')
            action = payload.get('action')
            return f"{event_type}:{action}:{pr_id}"
            
        else:
            # Generic fingerprint
            return f"{event_type}:{hash(str(payload))}"

    def _is_duplicate_event(self, fingerprint: str) -> bool:
        """Check if event was recently processed"""
        if fingerprint in self.event_cache:
            time_diff = datetime.now() - self.event_cache[fingerprint]
            return time_diff < self.rate_limit_window
        return False

    async def cleanup_event_cache(self) -> None:
        """Clean up old entries from event cache"""
        cutoff_time = datetime.now() - self.rate_limit_window
        expired_keys = [
            key for key, timestamp in self.event_cache.items()
            if timestamp < cutoff_time
        ]
        
        for key in expired_keys:
            del self.event_cache[key]
        
        if expired_keys:
            logger.debug("Cleaned up event cache", expired_count=len(expired_keys))

    def get_event_stats(self) -> Dict[str, Any]:
        """Get event processing statistics"""
        return {
            "cache_size": len(self.event_cache),
            "processors_count": len(self.processors),
            "rate_limit_window_seconds": self.rate_limit_window.total_seconds()
        }