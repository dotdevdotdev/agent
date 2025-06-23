"""
Processing orchestrator for complete Claude Code CLI workflow
"""

import asyncio
import structlog
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .worktree_manager import WorktreeManager, WorktreeSession, WorktreeStatus
from .prompt_builder import PromptBuilder, PromptContext, BuiltPrompt
from .result_processor import ResultProcessor, ParsedResult, GitHubOutput, OutputFormat
from .issue_parser import ParsedTask
from .github_client import GitHubClient
from .agent_state_machine import AgentStateMachine, AgentState

logger = structlog.get_logger()


class ProcessingStage(str, Enum):
    """Stages of processing workflow"""
    INITIALIZING = "initializing"
    CREATING_WORKTREE = "creating_worktree"
    BUILDING_PROMPT = "building_prompt"
    EXECUTING_CLAUDE = "executing_claude"
    PROCESSING_RESULTS = "processing_results"
    POSTING_TO_GITHUB = "posting_to_github"
    COMMITTING_CHANGES = "committing_changes"
    COMPLETING = "completing"
    CLEANING_UP = "cleaning_up"


@dataclass
class ProcessingContext:
    """Complete context for processing workflow"""
    job_id: str
    repository: str
    issue_number: int
    parsed_task: ParsedTask
    session: Optional[WorktreeSession] = None
    prompt_context: Optional[PromptContext] = None
    built_prompt: Optional[BuiltPrompt] = None
    parsed_result: Optional[ParsedResult] = None
    github_output: Optional[GitHubOutput] = None
    stage: ProcessingStage = ProcessingStage.INITIALIZING
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    error_message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class ProcessingOrchestratorError(Exception):
    """Custom exception for processing orchestrator errors"""
    def __init__(self, message: str, context: ProcessingContext = None, stage: ProcessingStage = None):
        self.message = message
        self.context = context
        self.stage = stage
        super().__init__(message)


class ProcessingOrchestrator:
    """Orchestrates the complete Claude Code CLI processing workflow"""

    def __init__(self,
                 worktree_manager: WorktreeManager = None,
                 prompt_builder: PromptBuilder = None,
                 result_processor: ResultProcessor = None,
                 github_client: GitHubClient = None,
                 state_machine: AgentStateMachine = None):
        
        self.worktree_manager = worktree_manager or WorktreeManager()
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.result_processor = result_processor or ResultProcessor()
        self.github_client = github_client or GitHubClient()
        self.state_machine = state_machine
        
        # Track active processing contexts
        self.active_contexts: Dict[str, ProcessingContext] = {}
        
        logger.info("Processing orchestrator initialized")

    async def process_issue(self,
                          job_id: str,
                          repository: str,
                          issue_number: int,
                          parsed_task: ParsedTask,
                          progress_callback: Callable[[str, int], None] = None) -> ProcessingContext:
        """Execute complete processing workflow for a GitHub issue"""
        
        context = ProcessingContext(
            job_id=job_id,
            repository=repository,
            issue_number=issue_number,
            parsed_task=parsed_task
        )
        
        self.active_contexts[job_id] = context
        
        try:
            # Stage 1: Initialize and create worktree
            await self._stage_create_worktree(context, progress_callback)
            
            # Stage 2: Build optimized prompt
            await self._stage_build_prompt(context, progress_callback)
            
            # Stage 3: Execute Claude Code CLI
            await self._stage_execute_claude(context, progress_callback)
            
            # Stage 4: Process results
            await self._stage_process_results(context, progress_callback)
            
            # Stage 5: Post to GitHub
            await self._stage_post_to_github(context, progress_callback)
            
            # Stage 6: Commit changes if any
            await self._stage_commit_changes(context, progress_callback)
            
            # Stage 7: Complete processing
            await self._stage_complete(context, progress_callback)
            
            return context
            
        except Exception as e:
            context.error_message = str(e)
            logger.error(
                "Processing workflow failed",
                job_id=job_id,
                stage=context.stage,
                error=str(e)
            )
            
            # Attempt cleanup
            try:
                await self._stage_cleanup(context, force=True)
            except Exception as cleanup_error:
                logger.error("Cleanup failed", job_id=job_id, error=str(cleanup_error))
            
            raise ProcessingOrchestratorError(f"Processing failed: {str(e)}", context, context.stage)
        
        finally:
            # Remove from active contexts
            if job_id in self.active_contexts:
                del self.active_contexts[job_id]

    async def _stage_create_worktree(self, 
                                   context: ProcessingContext,
                                   progress_callback: Callable[[str, int], None] = None) -> None:
        """Stage 1: Create isolated worktree"""
        context.stage = ProcessingStage.CREATING_WORKTREE
        
        if progress_callback:
            progress_callback("Creating isolated worktree for processing...", 10)
        
        # Update state machine
        if self.state_machine:
            await self.state_machine.transition_to(
                context.job_id, AgentState.ANALYZING,
                user_message="Creating isolated environment for processing..."
            )
        
        context.session = await self.worktree_manager.create_session(
            job_id=context.job_id,
            repository=context.repository,
            issue_number=context.issue_number,
            progress_callback=progress_callback
        )
        
        logger.info(
            "Worktree created",
            job_id=context.job_id,
            worktree_path=str(context.session.worktree_info.path)
        )

    async def _stage_build_prompt(self,
                                context: ProcessingContext,
                                progress_callback: Callable[[str, int], None] = None) -> None:
        """Stage 2: Build optimized prompt for Claude CLI"""
        context.stage = ProcessingStage.BUILDING_PROMPT
        
        if progress_callback:
            progress_callback("Building optimized prompt for Claude Code CLI...", 25)
        
        # Create prompt context
        context.prompt_context = PromptContext(
            repository_name=context.repository,
            issue_number=context.issue_number,
            job_id=context.job_id,
            working_directory=str(context.session.worktree_info.path)
        )
        
        # Build the prompt
        context.built_prompt = await self.prompt_builder.build_prompt(
            context.parsed_task,
            context.prompt_context
        )
        
        # Store metadata
        context.metadata.update({
            "prompt_template": context.built_prompt.template_used.value,
            "estimated_tokens": context.built_prompt.estimated_tokens,
            "prompt_truncated": context.built_prompt.truncated,
            "context_files": len(context.built_prompt.context_files)
        })
        
        logger.info(
            "Prompt built",
            job_id=context.job_id,
            template=context.built_prompt.template_used,
            estimated_tokens=context.built_prompt.estimated_tokens,
            truncated=context.built_prompt.truncated
        )

    async def _stage_execute_claude(self,
                                  context: ProcessingContext,
                                  progress_callback: Callable[[str, int], None] = None) -> None:
        """Stage 3: Execute Claude Code CLI"""
        context.stage = ProcessingStage.EXECUTING_CLAUDE
        
        if progress_callback:
            progress_callback("Executing Claude Code CLI analysis...", 40)
        
        # Update state machine
        if self.state_machine:
            await self.state_machine.transition_to(
                context.job_id, AgentState.IMPLEMENTING,
                user_message="Running Claude Code CLI analysis..."
            )
        
        # Execute Claude with the built prompt
        claude_result = await self.worktree_manager.process_with_claude(
            job_id=context.job_id,
            prompt=context.built_prompt.prompt,
            file_paths=context.built_prompt.context_files if context.built_prompt.context_files else None,
            timeout=None  # Use default timeout
        )
        
        # Store Claude execution result in context
        context.metadata["claude_execution"] = {
            "status": claude_result.status.value,
            "execution_time": claude_result.execution_time,
            "return_code": claude_result.return_code,
            "stdout_length": len(claude_result.stdout),
            "stderr_length": len(claude_result.stderr)
        }
        
        # Store the result for next stage
        context.session.claude_results = [claude_result]
        
        logger.info(
            "Claude execution completed",
            job_id=context.job_id,
            status=claude_result.status,
            execution_time=claude_result.execution_time
        )

    async def _stage_process_results(self,
                                   context: ProcessingContext,
                                   progress_callback: Callable[[str, int], None] = None) -> None:
        """Stage 4: Process Claude CLI results"""
        context.stage = ProcessingStage.PROCESSING_RESULTS
        
        if progress_callback:
            progress_callback("Processing Claude CLI results...", 60)
        
        # Get the Claude execution result
        claude_result = context.session.claude_results[0]
        
        # Process the result
        context.parsed_result = await self.result_processor.process_result(
            execution_result=claude_result,
            job_id=context.job_id,
            repository=context.repository,
            issue_number=context.issue_number
        )
        
        # Store result metadata
        context.metadata.update({
            "result_type": context.parsed_result.result_type.value,
            "confidence_score": context.parsed_result.confidence_score,
            "code_changes_count": len(context.parsed_result.code_changes),
            "recommendations_count": len(context.parsed_result.recommendations),
            "file_references_count": len(context.parsed_result.file_references)
        })
        
        logger.info(
            "Results processed",
            job_id=context.job_id,
            result_type=context.parsed_result.result_type,
            confidence=context.parsed_result.confidence_score,
            code_changes=len(context.parsed_result.code_changes)
        )

    async def _stage_post_to_github(self,
                                  context: ProcessingContext,
                                  progress_callback: Callable[[str, int], None] = None) -> None:
        """Stage 5: Post results to GitHub"""
        context.stage = ProcessingStage.POSTING_TO_GITHUB
        
        if progress_callback:
            progress_callback("Posting results to GitHub...", 75)
        
        # Determine output format based on results
        output_format = self._determine_output_format(context.parsed_result)
        
        # Format for GitHub
        context.github_output = await self.result_processor.format_for_github(
            context.parsed_result,
            output_format
        )
        
        # Post to GitHub
        github_results = await self.result_processor.post_to_github(
            context.github_output,
            context.repository,
            context.issue_number
        )
        
        # Store GitHub posting results
        context.metadata["github_posting"] = {
            "format_type": context.github_output.format_type.value,
            "primary_comment_id": github_results.get("primary_comment", {}).get("id"),
            "additional_comments_count": len(github_results.get("additional_comments", [])),
            "labels_added": len(context.github_output.suggested_labels)
        }
        
        logger.info(
            "Posted to GitHub",
            job_id=context.job_id,
            format_type=context.github_output.format_type,
            comment_id=github_results.get("primary_comment", {}).get("id")
        )

    async def _stage_commit_changes(self,
                                  context: ProcessingContext,
                                  progress_callback: Callable[[str, int], None] = None) -> None:
        """Stage 6: Commit changes if any were made"""
        context.stage = ProcessingStage.COMMITTING_CHANGES
        
        # Only commit if there were code changes and they were applied
        if (context.parsed_result and 
            context.parsed_result.code_changes and 
            context.github_output.format_type == OutputFormat.PULL_REQUEST):
            
            if progress_callback:
                progress_callback("Committing code changes...", 85)
            
            commit_message = f"Agent: {context.parsed_result.summary}"
            commit_hash = await self.worktree_manager.commit_changes(
                job_id=context.job_id,
                commit_message=commit_message,
                author_name="Claude Code Agent",
                author_email="agent@claude.ai"
            )
            
            if commit_hash:
                context.metadata["commit_hash"] = commit_hash
                logger.info("Changes committed", job_id=context.job_id, commit=commit_hash[:8])
        else:
            logger.info("No changes to commit", job_id=context.job_id)

    async def _stage_complete(self,
                            context: ProcessingContext,
                            progress_callback: Callable[[str, int], None] = None) -> None:
        """Stage 7: Complete processing"""
        context.stage = ProcessingStage.COMPLETING
        
        if progress_callback:
            progress_callback("Completing processing...", 95)
        
        # Complete the worktree session
        completed_session = await self.worktree_manager.complete_session(context.job_id)
        context.session = completed_session
        
        # Update state machine
        if self.state_machine:
            await self.state_machine.transition_to(
                context.job_id, AgentState.COMPLETED,
                user_message=f"Processing completed successfully! {context.parsed_result.summary if context.parsed_result else 'Task finished.'}"
            )
        
        context.completed_at = datetime.now()
        context.metadata["total_duration"] = (context.completed_at - context.started_at).total_seconds()
        
        # Schedule cleanup
        await self._stage_cleanup(context)
        
        if progress_callback:
            progress_callback("Processing completed successfully!", 100)
        
        logger.info(
            "Processing completed",
            job_id=context.job_id,
            duration=context.metadata["total_duration"],
            confidence=context.parsed_result.confidence_score if context.parsed_result else 0
        )

    async def _stage_cleanup(self,
                           context: ProcessingContext,
                           force: bool = False) -> None:
        """Final stage: Cleanup resources"""
        context.stage = ProcessingStage.CLEANING_UP
        
        try:
            # Cleanup worktree
            if context.session:
                cleanup_success = await self.worktree_manager.cleanup_session(
                    context.job_id, force=force
                )
                context.metadata["cleanup_success"] = cleanup_success
            
            logger.info("Cleanup completed", job_id=context.job_id, force=force)
            
        except Exception as e:
            logger.error("Cleanup failed", job_id=context.job_id, error=str(e))
            if not force:
                raise

    def _determine_output_format(self, parsed_result: ParsedResult) -> OutputFormat:
        """Determine the best output format based on results"""
        
        # If there are significant code changes, consider threaded comments
        if len(parsed_result.code_changes) > 2:
            return OutputFormat.THREADED_COMMENTS
        
        # For most cases, use markdown comment
        return OutputFormat.MARKDOWN_COMMENT

    async def get_processing_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get current processing status for a job"""
        if job_id not in self.active_contexts:
            return None
        
        context = self.active_contexts[job_id]
        
        return {
            "job_id": job_id,
            "stage": context.stage.value,
            "repository": context.repository,
            "issue_number": context.issue_number,
            "started_at": context.started_at.isoformat(),
            "duration_seconds": (datetime.now() - context.started_at).total_seconds(),
            "metadata": context.metadata,
            "error_message": context.error_message
        }

    async def cancel_processing(self, job_id: str) -> bool:
        """Cancel active processing"""
        if job_id not in self.active_contexts:
            return False
        
        try:
            context = self.active_contexts[job_id]
            
            # Cancel Claude execution if running
            if context.stage == ProcessingStage.EXECUTING_CLAUDE:
                claude_executions = self.worktree_manager.claude_service.get_active_executions()
                for exec_id in claude_executions:
                    if job_id in exec_id:
                        await self.worktree_manager.claude_service.cancel_execution(exec_id)
            
            # Cleanup
            await self._stage_cleanup(context, force=True)
            
            # Update state machine
            if self.state_machine:
                await self.state_machine.transition_to(
                    job_id, AgentState.CANCELLED,
                    user_message="Processing cancelled by request"
                )
            
            logger.info("Processing cancelled", job_id=job_id, stage=context.stage)
            return True
            
        except Exception as e:
            logger.error("Failed to cancel processing", job_id=job_id, error=str(e))
            return False

    async def get_health_status(self) -> Dict[str, Any]:
        """Get health status of all components"""
        try:
            worktree_health = await self.worktree_manager.health_check()
            
            return {
                "healthy": worktree_health.get("healthy", False),
                "active_processing": len(self.active_contexts),
                "components": {
                    "worktree_manager": worktree_health,
                    "prompt_builder": {"initialized": bool(self.prompt_builder)},
                    "result_processor": {"initialized": bool(self.result_processor)},
                    "github_client": {"initialized": bool(self.github_client)}
                },
                "active_jobs": list(self.active_contexts.keys())
            }
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e),
                "active_processing": len(self.active_contexts)
            }