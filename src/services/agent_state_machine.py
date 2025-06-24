"""
Advanced agent state management with GitHub integration
"""

import asyncio
import structlog
from enum import Enum
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .github_client import GitHubClient
from .job_manager import JobManager

logger = structlog.get_logger()


class AgentState(str, Enum):
    QUEUED = "agent:queued"
    VALIDATING = "agent:validating"  # New validation state
    ANALYZING = "agent:analyzing"  # New intermediate state
    IN_PROGRESS = "agent:in-progress"
    AWAITING_FEEDBACK = "agent:awaiting-feedback"
    IMPLEMENTING = "agent:implementing"  # New intermediate state
    TESTING = "agent:testing"  # New intermediate state
    COMPLETED = "agent:completed"
    FAILED = "agent:failed"
    CANCELLED = "agent:cancelled"
    ESCALATED = "agent:escalated"  # New escalation state


@dataclass
class StateTransition:
    from_state: AgentState
    to_state: AgentState
    condition: Optional[Callable] = None
    auto_transition_delay: Optional[timedelta] = None
    required_user_action: Optional[str] = None
    description: str = ""


@dataclass
class StateMetadata:
    progress_percentage: int
    user_message: str
    technical_details: Optional[str] = None
    estimated_completion: Optional[datetime] = None
    next_actions: List[str] = field(default_factory=list)
    can_cancel: bool = True
    can_retry: bool = False


@dataclass
class StateContext:
    job_id: str
    repository: str
    issue_number: int
    current_state: AgentState
    previous_state: Optional[AgentState] = None
    state_entered_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    error_count: int = 0
    retry_count: int = 0


class AgentStateMachine:
    """Manages agent state transitions and GitHub integration"""

    def __init__(self, github_client: GitHubClient, job_manager: JobManager):
        self.github_client = github_client
        self.job_manager = job_manager
        self.state_metadata = self._initialize_state_metadata()
        self.valid_transitions = self._initialize_transitions()
        self.active_contexts: Dict[str, StateContext] = {}
        self.feedback_timeouts: Dict[str, asyncio.Task] = {}

    async def initialize_context(self, job_id: str, repository: str, issue_number: int) -> StateContext:
        """Initialize state context for a new job"""
        context = StateContext(
            job_id=job_id,
            repository=repository,
            issue_number=issue_number,
            current_state=AgentState.QUEUED
        )
        self.active_contexts[job_id] = context
        
        logger.info(
            "State context initialized",
            job_id=job_id,
            repository=repository,
            issue_number=issue_number
        )
        
        return context

    async def transition_to(self, job_id: str, new_state: AgentState, 
                          context: Dict[str, Any] = None, 
                          user_message: str = None) -> bool:
        """Transition to new state with GitHub updates"""
        if job_id not in self.active_contexts:
            logger.error("No context found for job", job_id=job_id)
            return False

        job_context = self.active_contexts[job_id]
        current_state = job_context.current_state

        # Check if transition is valid
        if not self._is_valid_transition(current_state, new_state):
            logger.warning(
                "Invalid state transition attempted",
                job_id=job_id,
                from_state=current_state,
                to_state=new_state
            )
            return False

        # Update context
        job_context.previous_state = current_state
        job_context.current_state = new_state
        job_context.state_entered_at = datetime.now()
        if context:
            job_context.metadata.update(context)

        # Get state metadata
        metadata = self.state_metadata[new_state]
        
        # Update job status
        await self.job_manager.update_job_status(
            job_id, 
            self._map_state_to_job_status(new_state),
            progress=metadata.progress_percentage
        )

        # Update GitHub with new state
        await self._update_github_state(job_context, metadata, user_message)

        # Handle automatic transitions
        if metadata.next_actions:
            await self._schedule_next_actions(job_context)

        # Set up feedback timeout if needed
        if new_state == AgentState.AWAITING_FEEDBACK:
            await self._setup_feedback_timeout(job_context)

        logger.info(
            "State transition completed",
            job_id=job_id,
            from_state=current_state,
            to_state=new_state,
            progress=metadata.progress_percentage
        )

        return True

    async def update_progress(self, job_id: str, progress: int, message: str, 
                            technical_details: str = None) -> None:
        """Update progress without state change"""
        if job_id not in self.active_contexts:
            return

        job_context = self.active_contexts[job_id]
        job_context.metadata['last_progress_update'] = datetime.now()
        job_context.metadata['progress_message'] = message

        # Update job progress
        await self.job_manager.update_job_progress(job_id, progress, message)

        # Create progress comment on GitHub
        await self._create_progress_comment(job_context, progress, message, technical_details)

        logger.info(
            "Progress updated",
            job_id=job_id,
            progress=progress,
            message=message[:100]
        )

    async def request_user_feedback(self, job_id: str, feedback_request: str, 
                                  options: List[str] = None, timeout_hours: int = 24) -> None:
        """Request specific feedback from user"""
        if job_id not in self.active_contexts:
            return

        job_context = self.active_contexts[job_id]
        
        # Transition to awaiting feedback state
        await self.transition_to(job_id, AgentState.AWAITING_FEEDBACK, {
            'feedback_request': feedback_request,
            'feedback_options': options or [],
            'feedback_timeout': datetime.now() + timedelta(hours=timeout_hours)
        })

        # Create feedback request comment
        await self._create_feedback_request_comment(job_context, feedback_request, options)

    async def handle_user_response(self, job_id: str, comment_body: str, 
                                 commenter: str) -> None:
        """Process user response and continue workflow"""
        if job_id not in self.active_contexts:
            return

        job_context = self.active_contexts[job_id]
        
        # Cancel feedback timeout
        if job_id in self.feedback_timeouts:
            self.feedback_timeouts[job_id].cancel()
            del self.feedback_timeouts[job_id]

        # Parse user response
        response_data = self._parse_user_response(comment_body)
        job_context.metadata['user_response'] = response_data
        job_context.metadata['response_timestamp'] = datetime.now()

        # Determine next action based on response
        if response_data.get('action') == 'cancel':
            await self.transition_to(job_id, AgentState.CANCELLED)
        elif response_data.get('action') == 'retry':
            await self._handle_retry(job_context)
        elif response_data.get('action') == 'escalate':
            await self.transition_to(job_id, AgentState.ESCALATED)
        else:
            # Continue with normal processing
            await self.transition_to(job_id, AgentState.IN_PROGRESS, {
                'feedback_received': True,
                'user_feedback': response_data
            })

        logger.info(
            "User response processed",
            job_id=job_id,
            commenter=commenter,
            action=response_data.get('action', 'continue')
        )

    async def handle_error(self, job_id: str, error: Exception, 
                         can_retry: bool = True) -> None:
        """Handle error and determine recovery strategy"""
        if job_id not in self.active_contexts:
            return

        job_context = self.active_contexts[job_id]
        job_context.error_count += 1
        job_context.metadata['last_error'] = {
            'error': str(error),
            'timestamp': datetime.now(),
            'error_type': type(error).__name__
        }

        # Determine error handling strategy
        if job_context.error_count >= 3:
            # Too many errors, escalate
            await self.transition_to(job_id, AgentState.ESCALATED, {
                'escalation_reason': 'Multiple errors occurred',
                'error_count': job_context.error_count
            })
        elif can_retry and job_context.retry_count < 2:
            # Retry with delay
            await asyncio.sleep(2 ** job_context.retry_count)  # Exponential backoff
            job_context.retry_count += 1
            await self.transition_to(job_id, AgentState.IN_PROGRESS, {
                'retrying': True,
                'retry_count': job_context.retry_count
            })
        else:
            # Mark as failed
            await self.transition_to(job_id, AgentState.FAILED, {
                'failure_reason': str(error),
                'error_count': job_context.error_count
            })

        logger.error(
            "Error handled in state machine",
            job_id=job_id,
            error=str(error),
            error_count=job_context.error_count,
            retry_count=job_context.retry_count
        )

    async def cleanup_context(self, job_id: str) -> None:
        """Clean up state context when job is complete"""
        if job_id in self.active_contexts:
            del self.active_contexts[job_id]
        
        if job_id in self.feedback_timeouts:
            self.feedback_timeouts[job_id].cancel()
            del self.feedback_timeouts[job_id]

        logger.info("State context cleaned up", job_id=job_id)

    def get_context(self, job_id: str) -> Optional[StateContext]:
        """Get current state context"""
        return self.active_contexts.get(job_id)

    def _initialize_state_metadata(self) -> Dict[AgentState, StateMetadata]:
        """Initialize metadata for each state"""
        return {
            AgentState.QUEUED: StateMetadata(
                progress_percentage=0,
                user_message="Your task has been queued and will be processed shortly.",
                next_actions=["validate_task"]
            ),
            AgentState.VALIDATING: StateMetadata(
                progress_percentage=5,
                user_message="Validating task requirements and checking for completeness.",
                next_actions=["start_analysis"]
            ),
            AgentState.ANALYZING: StateMetadata(
                progress_percentage=15,
                user_message="Analyzing the task and planning the approach.",
                next_actions=["begin_implementation"]
            ),
            AgentState.IN_PROGRESS: StateMetadata(
                progress_percentage=30,
                user_message="Processing your request. This may take a while for complex tasks.",
                next_actions=["continue_processing"]
            ),
            AgentState.IMPLEMENTING: StateMetadata(
                progress_percentage=60,
                user_message="Implementing the solution based on the analysis.",
                next_actions=["run_tests"]
            ),
            AgentState.TESTING: StateMetadata(
                progress_percentage=80,
                user_message="Testing the implementation and validating results.",
                next_actions=["finalize_results"]
            ),
            AgentState.AWAITING_FEEDBACK: StateMetadata(
                progress_percentage=50,
                user_message="Waiting for your feedback to continue processing.",
                next_actions=[],
                can_cancel=True
            ),
            AgentState.COMPLETED: StateMetadata(
                progress_percentage=100,
                user_message="Task completed successfully! Results are ready.",
                next_actions=[],
                can_cancel=False,
                can_retry=False
            ),
            AgentState.FAILED: StateMetadata(
                progress_percentage=0,
                user_message="Task failed to complete. Please check the error details.",
                next_actions=[],
                can_cancel=False,
                can_retry=True
            ),
            AgentState.CANCELLED: StateMetadata(
                progress_percentage=0,
                user_message="Task was cancelled by user request.",
                next_actions=[],
                can_cancel=False,
                can_retry=True
            ),
            AgentState.ESCALATED: StateMetadata(
                progress_percentage=0,
                user_message="Task has been escalated for human review.",
                next_actions=[],
                can_cancel=True,
                can_retry=False
            )
        }

    def _initialize_transitions(self) -> Dict[AgentState, List[StateTransition]]:
        """Define valid state transitions"""
        return {
            AgentState.QUEUED: [
                StateTransition(AgentState.QUEUED, AgentState.VALIDATING, description="Start validation"),
                StateTransition(AgentState.QUEUED, AgentState.CANCELLED, description="Cancel before processing")
            ],
            AgentState.VALIDATING: [
                StateTransition(AgentState.VALIDATING, AgentState.ANALYZING, description="Validation passed"),
                StateTransition(AgentState.VALIDATING, AgentState.IN_PROGRESS, description="Skip analysis for simple tasks"),
                StateTransition(AgentState.VALIDATING, AgentState.COMPLETED, description="Simple task completed directly"),
                StateTransition(AgentState.VALIDATING, AgentState.AWAITING_FEEDBACK, description="Need user clarification"),
                StateTransition(AgentState.VALIDATING, AgentState.FAILED, description="Validation failed")
            ],
            AgentState.ANALYZING: [
                StateTransition(AgentState.ANALYZING, AgentState.IN_PROGRESS, description="Analysis complete"),
                StateTransition(AgentState.ANALYZING, AgentState.AWAITING_FEEDBACK, description="Need user input"),
                StateTransition(AgentState.ANALYZING, AgentState.FAILED, description="Analysis failed")
            ],
            AgentState.IN_PROGRESS: [
                StateTransition(AgentState.IN_PROGRESS, AgentState.IMPLEMENTING, description="Start implementation"),
                StateTransition(AgentState.IN_PROGRESS, AgentState.AWAITING_FEEDBACK, description="Need user feedback"),
                StateTransition(AgentState.IN_PROGRESS, AgentState.FAILED, description="Processing failed"),
                StateTransition(AgentState.IN_PROGRESS, AgentState.CANCELLED, description="User cancelled")
            ],
            AgentState.IMPLEMENTING: [
                StateTransition(AgentState.IMPLEMENTING, AgentState.TESTING, description="Implementation complete"),
                StateTransition(AgentState.IMPLEMENTING, AgentState.COMPLETED, description="Simple task complete"),
                StateTransition(AgentState.IMPLEMENTING, AgentState.FAILED, description="Implementation failed")
            ],
            AgentState.TESTING: [
                StateTransition(AgentState.TESTING, AgentState.COMPLETED, description="Tests passed"),
                StateTransition(AgentState.TESTING, AgentState.FAILED, description="Tests failed"),
                StateTransition(AgentState.TESTING, AgentState.IMPLEMENTING, description="Need to fix issues")
            ],
            AgentState.AWAITING_FEEDBACK: [
                StateTransition(AgentState.AWAITING_FEEDBACK, AgentState.IN_PROGRESS, description="Feedback received"),
                StateTransition(AgentState.AWAITING_FEEDBACK, AgentState.CANCELLED, description="User cancelled"),
                StateTransition(AgentState.AWAITING_FEEDBACK, AgentState.ESCALATED, description="Timeout or escalation")
            ],
            AgentState.FAILED: [
                StateTransition(AgentState.FAILED, AgentState.IN_PROGRESS, description="Retry processing"),
                StateTransition(AgentState.FAILED, AgentState.ESCALATED, description="Escalate to human")
            ],
            AgentState.CANCELLED: [
                StateTransition(AgentState.CANCELLED, AgentState.QUEUED, description="Restart task")
            ],
            AgentState.ESCALATED: [
                StateTransition(AgentState.ESCALATED, AgentState.IN_PROGRESS, description="Resume processing")
            ]
        }

    def _is_valid_transition(self, from_state: AgentState, to_state: AgentState) -> bool:
        """Check if state transition is valid"""
        if from_state not in self.valid_transitions:
            return False
        
        valid_transitions = self.valid_transitions[from_state]
        return any(transition.to_state == to_state for transition in valid_transitions)

    def _map_state_to_job_status(self, state: AgentState) -> str:
        """Map agent state to job status"""
        mapping = {
            AgentState.QUEUED: "pending",
            AgentState.VALIDATING: "running",
            AgentState.ANALYZING: "running",
            AgentState.IN_PROGRESS: "running",
            AgentState.IMPLEMENTING: "running",
            AgentState.TESTING: "running",
            AgentState.AWAITING_FEEDBACK: "running",
            AgentState.COMPLETED: "completed",
            AgentState.FAILED: "failed",
            AgentState.CANCELLED: "cancelled",
            AgentState.ESCALATED: "failed"
        }
        return mapping.get(state, "running")

    async def _update_github_state(self, context: StateContext, metadata: StateMetadata, 
                                 user_message: str = None) -> None:
        """Update GitHub with new state"""
        try:
            # Remove old state label and add new one
            if context.previous_state:
                await self.github_client.remove_label(
                    context.repository, context.issue_number, context.previous_state.value
                )
            
            await self.github_client.add_label(
                context.repository, context.issue_number, context.current_state.value
            )

            # Create state transition comment
            message = user_message or metadata.user_message
            await self.github_client.create_comment(
                context.repository, 
                context.issue_number,
                f"🤖 **State Update**: {context.current_state.value}\n\n{message}\n\n" +
                f"Progress: {metadata.progress_percentage}%"
            )

        except Exception as e:
            logger.error("Failed to update GitHub state", error=str(e), job_id=context.job_id)

    async def _create_progress_comment(self, context: StateContext, progress: int, 
                                     message: str, technical_details: str = None) -> None:
        """Create progress update comment"""
        try:
            comment_body = f"📊 **Progress Update**: {progress}%\n\n{message}"
            if technical_details:
                comment_body += f"\n\n<details><summary>Technical Details</summary>\n\n{technical_details}\n</details>"

            await self.github_client.create_comment(
                context.repository, context.issue_number, comment_body
            )
        except Exception as e:
            logger.error("Failed to create progress comment", error=str(e), job_id=context.job_id)

    async def _create_feedback_request_comment(self, context: StateContext, 
                                             feedback_request: str, options: List[str] = None) -> None:
        """Create feedback request comment"""
        try:
            comment_body = f"❓ **Feedback Needed**\n\n{feedback_request}"
            
            if options:
                comment_body += "\n\nPlease respond with one of the following options:"
                for i, option in enumerate(options, 1):
                    comment_body += f"\n{i}. {option}"
            
            comment_body += "\n\nYou can also use these commands:\n"
            comment_body += "- `/cancel` - Cancel this task\n"
            comment_body += "- `/retry` - Retry from the beginning\n"
            comment_body += "- `/escalate` - Escalate to human review"

            await self.github_client.create_comment(
                context.repository, context.issue_number, comment_body
            )
        except Exception as e:
            logger.error("Failed to create feedback request", error=str(e), job_id=context.job_id)

    def _parse_user_response(self, comment_body: str) -> Dict[str, Any]:
        """Parse user response for commands and feedback"""
        response_data = {'raw_response': comment_body}
        
        # Check for commands
        if '/cancel' in comment_body.lower():
            response_data['action'] = 'cancel'
        elif '/retry' in comment_body.lower():
            response_data['action'] = 'retry'
        elif '/escalate' in comment_body.lower():
            response_data['action'] = 'escalate'
        else:
            response_data['action'] = 'continue'
            response_data['feedback'] = comment_body.strip()

        return response_data

    async def _setup_feedback_timeout(self, context: StateContext) -> None:
        """Set up timeout for feedback request"""
        timeout_hours = context.metadata.get('feedback_timeout_hours', 24)
        
        async def timeout_handler():
            await asyncio.sleep(timeout_hours * 3600)  # Convert to seconds
            if context.job_id in self.active_contexts:
                await self.transition_to(context.job_id, AgentState.ESCALATED, {
                    'escalation_reason': 'Feedback timeout',
                    'timeout_hours': timeout_hours
                })

        self.feedback_timeouts[context.job_id] = asyncio.create_task(timeout_handler())

    async def _handle_retry(self, context: StateContext) -> None:
        """Handle retry logic"""
        context.retry_count += 1
        context.error_count = 0  # Reset error count on explicit retry
        
        if context.retry_count <= 3:
            await self.transition_to(context.job_id, AgentState.QUEUED, {
                'retrying': True,
                'retry_count': context.retry_count
            })
        else:
            await self.transition_to(context.job_id, AgentState.ESCALATED, {
                'escalation_reason': 'Too many retries',
                'retry_count': context.retry_count
            })

    async def _schedule_next_actions(self, context: StateContext) -> None:
        """Schedule automatic next actions if needed"""
        # This can be extended to handle automatic state transitions
        # For now, it's a placeholder for future functionality
        pass