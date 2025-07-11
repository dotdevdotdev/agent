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
from .result_processor import ResultProcessor, ParsedResult, GitHubOutput, OutputFormat, ResultType
from .issue_parser import ParsedTask, TaskType, OutputFormat as IssueOutputFormat
from .github_client import GitHubClient
from .agent_state_machine import AgentStateMachine, AgentState
from .agent_config_service import AgentConfigService
from src.models.configuration import AgentConfig

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
    agent_config: Optional[AgentConfig] = None
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
                 state_machine: AgentStateMachine = None,
                 agent_config_service: AgentConfigService = None):
        
        self.worktree_manager = worktree_manager or WorktreeManager()
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.result_processor = result_processor or ResultProcessor()
        self.github_client = github_client or GitHubClient()
        self.state_machine = state_machine
        self.agent_config_service = agent_config_service or AgentConfigService()
        
        # Track active processing contexts
        self.active_contexts: Dict[str, ProcessingContext] = {}
        
        logger.info("Processing orchestrator initialized")

    async def process_issue(self,
                          job_id: str,
                          repository: str,
                          issue_number: int,
                          parsed_task: ParsedTask,
                          progress_callback: Callable[[str, int], None] = None,
                          agent_id: str = None) -> ProcessingContext:
        """Execute complete processing workflow for a GitHub issue"""
        
        # Load agent configuration (prefer agent_id from parsed_task if available)
        effective_agent_id = getattr(parsed_task, 'agent_id', None) or agent_id
        agent_config = await self.agent_config_service.get_agent_config(effective_agent_id)
        
        context = ProcessingContext(
            job_id=job_id,
            repository=repository,
            issue_number=issue_number,
            parsed_task=parsed_task,
            agent_config=agent_config
        )
        
        # Store agent info in metadata
        context.metadata.update({
            "agent_name": agent_config.name,
            "agent_id": effective_agent_id,
            "agent_capabilities": agent_config.capabilities,
            "agent_timeout": agent_config.timeout_seconds
        })
        
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

    async def process_general_question(self,
                                     job_id: str,
                                     repository: str,
                                     issue_number: int,
                                     parsed_task: ParsedTask,
                                     progress_callback: Callable[[str, int], None] = None,
                                     agent_id: str = None) -> ProcessingContext:
        """Simplified processing workflow for general questions (no git worktree needed)"""
        
        # Load agent configuration (prefer agent_id from parsed_task if available)
        effective_agent_id = getattr(parsed_task, 'agent_id', None) or agent_id
        agent_config = await self.agent_config_service.get_agent_config(effective_agent_id)
        
        context = ProcessingContext(
            job_id=job_id,
            repository=repository,
            issue_number=issue_number,
            parsed_task=parsed_task,
            agent_config=agent_config
        )
        
        # Store agent info in metadata
        context.metadata.update({
            "agent_name": agent_config.name,
            "agent_id": effective_agent_id,
            "is_general_question": True
        })
        
        self.active_contexts[job_id] = context
        
        try:
            # Stage 1: Build simple prompt for general question
            await self._stage_build_simple_prompt(context, progress_callback)
            
            # Stage 2: Execute Claude for text response only
            await self._stage_execute_claude_simple(context, progress_callback)
            
            # Stage 3: Process text-only results
            await self._stage_process_simple_results(context, progress_callback)
            
            # Stage 4: Post response to GitHub
            await self._stage_post_simple_response(context, progress_callback)
            
            # Stage 5: Complete processing
            await self._stage_complete_simple(context, progress_callback)
            
            return context
            
        except Exception as e:
            context.error_message = str(e)
            logger.error("General question processing failed", error=str(e), job_id=job_id)
            raise ProcessingOrchestratorError(f"General question processing failed: {str(e)}", context, context.stage)
        
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
            await progress_callback("Creating isolated worktree for processing...", 10)
        
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
            await progress_callback("Building optimized prompt for Claude Code CLI...", 25)
        
        # Create prompt context with agent configuration
        context.prompt_context = PromptContext(
            repository_name=context.repository,
            issue_number=context.issue_number,
            job_id=context.job_id,
            working_directory=str(context.session.worktree_info.path)
        )
        
        # Get agent context files
        agent_context_files = await self.agent_config_service.get_context_files(context.agent_config)
        
        # Build the prompt with agent-specific system prompt and context
        agent_context = {
            "repository_info": {"name": context.repository},
            "task_type": context.parsed_task.task_type.value if hasattr(context.parsed_task.task_type, 'value') else str(context.parsed_task.task_type)
        }
        
        # Get enhanced system prompt from agent config
        enhanced_system_prompt = await self.agent_config_service.get_system_prompt(
            context.agent_config, agent_context
        )
        
        # Build the prompt with standard method
        context.built_prompt = await self.prompt_builder.build_prompt(
            context.parsed_task,
            context.prompt_context
        )
        
        # Enhance with agent-specific system prompt
        original_prompt = context.built_prompt.prompt
        enhanced_prompt = f"{enhanced_system_prompt}\n\n{original_prompt}"
        
        # Update the built prompt with enhanced content
        context.built_prompt.prompt = enhanced_prompt
        context.built_prompt.context_files.extend(agent_context_files)
        
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
            await progress_callback("Executing Claude Code CLI analysis...", 40)
        
        # Update state machine to IN_PROGRESS (proper transition from ANALYZING)
        if self.state_machine:
            await self.state_machine.transition_to(
                context.job_id, AgentState.IN_PROGRESS,
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
            await progress_callback("Processing Claude CLI results...", 60)
        
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
            await progress_callback("Posting results to GitHub...", 75)
        
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
                await progress_callback("Committing code changes...", 85)
            
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
            await progress_callback("Completing processing...", 95)
        
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
            await progress_callback("Processing completed successfully!", 100)
        
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

    # Simple processing stages for general questions
    
    async def _stage_build_simple_prompt(self,
                                       context: ProcessingContext,
                                       progress_callback: Callable[[str, int], None] = None) -> None:
        """Build simple prompt for general questions without file context"""
        context.stage = ProcessingStage.BUILDING_PROMPT
        
        if progress_callback:
            await progress_callback("Building prompt for general question...", 20)
        
        # Create minimal prompt context for general questions
        context.prompt_context = PromptContext(
            repository_name=context.repository,
            issue_number=context.issue_number,
            job_id=context.job_id,
            working_directory="",  # No specific directory for general questions
            file_contents={},  # No files for general questions
            repository_structure=[]
        )
        
        # Build the prompt
        context.built_prompt = self.prompt_builder.build_simple_question_prompt(
            context.prompt_context, context.parsed_task
        )
        
        logger.info("Simple prompt built", job_id=context.job_id, prompt_length=len(context.built_prompt.prompt))

    async def _stage_execute_claude_simple(self,
                                         context: ProcessingContext,
                                         progress_callback: Callable[[str, int], None] = None) -> None:
        """Execute Claude CLI for simple text response"""
        context.stage = ProcessingStage.EXECUTING_CLAUDE
        
        if progress_callback:
            await progress_callback("Generating response...", 60)
        
        # Execute Claude with simple prompt - no worktree needed
        execution_result = await self.worktree_manager.claude_service.execute_simple_prompt(
            context.built_prompt.prompt,
            execution_id=f"simple-{context.job_id}"
        )
        
        context.metadata["claude_execution"] = {
            "status": execution_result.status,
            "execution_time": execution_result.execution_time,
            "return_code": execution_result.return_code,
            "stdout": execution_result.stdout,
            "stderr": execution_result.stderr
        }
        
        logger.info("Simple Claude execution completed", 
                   job_id=context.job_id, 
                   status=execution_result.status,
                   execution_time=execution_result.execution_time)

    async def _stage_process_simple_results(self,
                                          context: ProcessingContext,
                                          progress_callback: Callable[[str, int], None] = None) -> None:
        """Process simple text results"""
        context.stage = ProcessingStage.PROCESSING_RESULTS
        
        if progress_callback:
            await progress_callback("Processing response...", 80)
        
        # Get the Claude execution result
        claude_result = context.metadata.get("claude_execution", {})
        
        # Create simple parsed result for text response
        context.parsed_result = ParsedResult(
            result_type=ResultType.ANALYSIS_REPORT,
            summary="General question answered",
            detailed_analysis=claude_result.get("stdout", ""),
            confidence_score=95.0,  # High confidence for simple questions
            metadata={
                "is_general_response": True,
                "execution_time": claude_result.get("execution_time", 0),
                "has_code_changes": False,
                "has_new_files": False,
                "output_format": OutputFormat.THREADED_COMMENTS.value,
                "raw_output": claude_result.get("stdout", "")
            }
        )
        
        # Generate GitHub-formatted output
        context.github_output = self.result_processor.format_simple_response(
            context.parsed_result,
            context.parsed_task
        )
        
        logger.info("Simple results processed", job_id=context.job_id)

    async def _stage_post_simple_response(self,
                                        context: ProcessingContext,
                                        progress_callback: Callable[[str, int], None] = None) -> None:
        """Post simple response to GitHub"""
        context.stage = ProcessingStage.POSTING_TO_GITHUB
        
        if progress_callback:
            await progress_callback("Posting response to GitHub...", 90)
        
        # Post the response as a comment
        await self.github_client.create_comment(
            context.repository,
            context.issue_number,
            context.github_output.primary_comment
        )
        
        # Update labels to indicate completion
        await self.github_client.add_labels(
            context.repository,
            context.issue_number,
            ["agent:completed"]
        )
        
        # Remove processing labels
        try:
            await self.github_client.remove_label(context.repository, context.issue_number, "agent:in-progress")
        except:
            pass  # Label might not exist
        try:
            await self.github_client.remove_label(context.repository, context.issue_number, "agent:queued")
        except:
            pass  # Label might not exist
        
        logger.info("Simple response posted to GitHub", job_id=context.job_id)

    async def _stage_complete_simple(self,
                                   context: ProcessingContext,
                                   progress_callback: Callable[[str, int], None] = None) -> None:
        """Complete simple processing"""
        context.stage = ProcessingStage.COMPLETING
        context.completed_at = datetime.now()
        
        if progress_callback:
            await progress_callback("✅ General question answered!", 100)
        
        # Update state machine
        if self.state_machine:
            await self.state_machine.transition_to(
                context.job_id, AgentState.COMPLETED,
                user_message="✅ General question answered successfully!"
            )
        
        logger.info("Simple processing completed", 
                   job_id=context.job_id,
                   total_time=(context.completed_at - context.started_at).total_seconds())