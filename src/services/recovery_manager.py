"""
Manages error recovery and escalation processes
"""

import asyncio
import structlog
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

from .github_client import GitHubClient
from .agent_state_machine import AgentStateMachine, AgentState
from .error_classifier import ErrorClassifier, ErrorAnalysis, ErrorCategory, ErrorSeverity

logger = structlog.get_logger()


class RecoveryManager:
    """Manages error recovery and escalation"""

    def __init__(self, github_client: GitHubClient, state_machine: AgentStateMachine):
        self.github_client = github_client
        self.state_machine = state_machine
        self.classifier = ErrorClassifier()
        self.recovery_attempts: Dict[str, int] = {}
        self.escalated_jobs: Dict[str, datetime] = {}

    async def handle_error(self, job_id: str, error: Exception, 
                          context: Dict[str, Any]) -> bool:
        """Handle error with appropriate recovery strategy"""
        logger.info("Handling error for job", job_id=job_id, error_type=type(error).__name__)

        try:
            # Classify the error
            analysis = self.classifier.classify_error(error, context)
            
            # Update job context with error info
            job_context = self.state_machine.get_context(job_id)
            if job_context:
                job_context.metadata['last_error'] = {
                    'error': str(error),
                    'analysis': analysis.__dict__,
                    'timestamp': datetime.now()
                }

            # Attempt automatic recovery
            recovery_successful = False
            if analysis.is_retryable and not analysis.escalation_required:
                recovery_successful = await self.attempt_automatic_recovery(job_id, analysis, context)

            # If recovery failed or escalation required, escalate
            if not recovery_successful or analysis.escalation_required:
                await self.escalate_to_human(job_id, analysis, context)
                return False

            return recovery_successful

        except Exception as e:
            logger.error("Error in recovery manager", job_id=job_id, error=str(e))
            await self.escalate_to_human(job_id, None, context)
            return False

    async def attempt_automatic_recovery(self, job_id: str, error_analysis: ErrorAnalysis,
                                       context: Dict[str, Any]) -> bool:
        """Attempt automatic recovery based on error analysis"""
        
        # Check if we've already tried too many times
        attempt_count = self.recovery_attempts.get(job_id, 0)
        if attempt_count >= error_analysis.max_retries:
            logger.info("Max recovery attempts reached", job_id=job_id)
            return False

        # Increment attempt count
        self.recovery_attempts[job_id] = attempt_count + 1

        # Get retry delay
        delay = self.classifier.get_retry_delay(None, attempt_count, error_analysis)
        
        # Wait if needed
        if delay > 0:
            logger.info("Waiting before retry", job_id=job_id, delay=delay)
            await asyncio.sleep(delay)

        # Attempt specific recovery based on error category
        recovery_method = self._get_recovery_method(error_analysis.category)
        if recovery_method:
            try:
                success = await recovery_method(job_id, error_analysis, context)
                if success:
                    logger.info("Automatic recovery successful", job_id=job_id)
                    return True
            except Exception as e:
                logger.error("Recovery method failed", job_id=job_id, error=str(e))

        return False

    async def escalate_to_human(self, job_id: str, error_analysis: Optional[ErrorAnalysis],
                               escalation_context: Dict[str, Any]) -> None:
        """Escalate error to human intervention"""
        
        self.escalated_jobs[job_id] = datetime.now()
        
        # Get job context
        job_context = self.state_machine.get_context(job_id)
        if not job_context:
            logger.error("No job context found for escalation", job_id=job_id)
            return

        # Determine escalation reason
        if error_analysis:
            reason = f"{error_analysis.category.value} - {error_analysis.user_message}"
        else:
            reason = "Critical error in recovery system"

        # Create escalation context
        escalation_info = {
            'escalation_reason': reason,
            'error_analysis': error_analysis.__dict__ if error_analysis else None,
            'recovery_attempts': self.recovery_attempts.get(job_id, 0),
            'job_context': job_context.__dict__,
            'escalation_time': datetime.now()
        }

        try:
            # Transition to escalated state
            await self.state_machine.transition_to(
                job_id, AgentState.ESCALATED,
                escalation_info,
                f"Task escalated: {reason}"
            )

            # Create GitHub escalation comment
            await self.github_client.create_escalation_comment(
                job_context.repository, job_context.issue_number,
                reason, escalation_info
            )

            logger.info("Job escalated to human review", job_id=job_id, reason=reason)

        except Exception as e:
            logger.error("Failed to escalate job", job_id=job_id, error=str(e))

    async def check_escalated_jobs(self) -> List[Dict[str, Any]]:
        """Check status of escalated jobs"""
        escalated_status = []
        
        for job_id, escalation_time in self.escalated_jobs.items():
            time_since_escalation = datetime.now() - escalation_time
            
            escalated_status.append({
                'job_id': job_id,
                'escalation_time': escalation_time,
                'hours_escalated': time_since_escalation.total_seconds() / 3600,
                'needs_follow_up': time_since_escalation > timedelta(hours=24)
            })

        return escalated_status

    async def resolve_escalated_job(self, job_id: str, resolution: str) -> bool:
        """Mark escalated job as resolved"""
        if job_id in self.escalated_jobs:
            del self.escalated_jobs[job_id]
            
            # Clean up recovery attempts
            if job_id in self.recovery_attempts:
                del self.recovery_attempts[job_id]

            logger.info("Escalated job resolved", job_id=job_id, resolution=resolution)
            return True
        
        return False

    async def report_error_statistics(self) -> Dict[str, Any]:
        """Generate error statistics and trends"""
        stats = self.classifier.get_error_statistics(24)  # Last 24 hours
        
        # Add recovery manager specific stats
        stats.update({
            'active_recovery_attempts': len(self.recovery_attempts),
            'escalated_jobs': len(self.escalated_jobs),
            'avg_recovery_attempts': sum(self.recovery_attempts.values()) / max(1, len(self.recovery_attempts))
        })

        return stats

    def _get_recovery_method(self, category: ErrorCategory):
        """Get appropriate recovery method for error category"""
        recovery_methods = {
            ErrorCategory.RATE_LIMIT: self._recover_rate_limit,
            ErrorCategory.NETWORK_ERROR: self._recover_network_error,
            ErrorCategory.TIMEOUT_ERROR: self._recover_timeout_error,
            ErrorCategory.API_ERROR: self._recover_api_error,
            ErrorCategory.PROCESSING_ERROR: self._recover_processing_error
        }
        
        return recovery_methods.get(category)

    async def _recover_rate_limit(self, job_id: str, analysis: ErrorAnalysis, 
                                context: Dict[str, Any]) -> bool:
        """Recover from rate limit errors"""
        # Rate limits are handled by exponential backoff
        # Just restart the job after the delay
        await self.state_machine.transition_to(
            job_id, AgentState.IN_PROGRESS,
            {'recovery_type': 'rate_limit_backoff'},
            "Resuming after rate limit delay"
        )
        return True

    async def _recover_network_error(self, job_id: str, analysis: ErrorAnalysis,
                                   context: Dict[str, Any]) -> bool:
        """Recover from network errors"""
        # Simple retry for network errors
        await self.state_machine.transition_to(
            job_id, AgentState.IN_PROGRESS,
            {'recovery_type': 'network_retry'},
            "Retrying after network error"
        )
        return True

    async def _recover_timeout_error(self, job_id: str, analysis: ErrorAnalysis,
                                   context: Dict[str, Any]) -> bool:
        """Recover from timeout errors"""
        # Try breaking down the task or using different approach
        job_context = self.state_machine.get_context(job_id)
        if job_context and job_context.metadata.get('complexity_reduced'):
            # Already tried reducing complexity, escalate
            return False
        
        # Mark as complexity reduced and retry
        await self.state_machine.transition_to(
            job_id, AgentState.IN_PROGRESS,
            {'recovery_type': 'complexity_reduction', 'complexity_reduced': True},
            "Retrying with reduced complexity"
        )
        return True

    async def _recover_api_error(self, job_id: str, analysis: ErrorAnalysis,
                               context: Dict[str, Any]) -> bool:
        """Recover from API errors"""
        # Simple retry for transient API errors
        if analysis.severity in [ErrorSeverity.LOW, ErrorSeverity.MEDIUM]:
            await self.state_machine.transition_to(
                job_id, AgentState.IN_PROGRESS,
                {'recovery_type': 'api_retry'},
                "Retrying after API error"
            )
            return True
        
        return False

    async def _recover_processing_error(self, job_id: str, analysis: ErrorAnalysis,
                                      context: Dict[str, Any]) -> bool:
        """Recover from processing errors"""
        # Try alternative processing approach
        job_context = self.state_machine.get_context(job_id)
        if job_context and job_context.metadata.get('alternative_approach'):
            # Already tried alternative approach
            return False
        
        await self.state_machine.transition_to(
            job_id, AgentState.IN_PROGRESS,
            {'recovery_type': 'alternative_approach', 'alternative_approach': True},
            "Retrying with alternative approach"
        )
        return True