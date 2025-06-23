"""
Comprehensive worktree management system for isolated issue processing
"""

import asyncio
import shutil
import structlog
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from .git_service import GitService, WorktreeInfo, GitServiceError
from .claude_code_service import ClaudeCodeService, ClaudeExecutionResult, ClaudeCodeServiceError
from config.settings import settings

logger = structlog.get_logger()


class WorktreeStatus(str, Enum):
    """Status of a worktree processing session"""
    CREATING = "creating"
    READY = "ready"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CLEANUP = "cleanup"
    DESTROYED = "destroyed"


@dataclass
class WorktreeSession:
    """Complete session information for worktree processing"""
    job_id: str
    repository: str
    issue_number: int
    status: WorktreeStatus
    worktree_info: Optional[WorktreeInfo] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_processing_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    claude_results: List[ClaudeExecutionResult] = field(default_factory=list)
    error_message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    files_modified: List[str] = field(default_factory=list)
    files_created: List[str] = field(default_factory=list)
    commits_made: List[str] = field(default_factory=list)
    progress_callback: Optional[Callable[[str, int], None]] = None


class WorktreeManagerError(Exception):
    """Custom exception for worktree manager errors"""
    def __init__(self, message: str, job_id: str = None, session: WorktreeSession = None):
        self.message = message
        self.job_id = job_id
        self.session = session
        super().__init__(message)


class WorktreeManager:
    """Comprehensive worktree management system"""

    def __init__(self, git_service: GitService = None, claude_service: ClaudeCodeService = None):
        self.git_service = git_service or GitService()
        self.claude_service = claude_service or ClaudeCodeService()
        self.active_sessions: Dict[str, WorktreeSession] = {}
        self.cleanup_tasks: Dict[str, asyncio.Task] = {}
        
        # Configuration
        self.max_concurrent_sessions = settings.MAX_CONCURRENT_JOBS
        self.session_timeout = timedelta(hours=2)  # Auto-cleanup after 2 hours
        self.auto_cleanup_enabled = True
        
        logger.info(
            "Worktree manager initialized",
            max_concurrent_sessions=self.max_concurrent_sessions,
            git_service_ready=bool(self.git_service),
            claude_service_ready=bool(self.claude_service)
        )

    async def create_session(self, 
                           job_id: str, 
                           repository: str, 
                           issue_number: int,
                           progress_callback: Callable[[str, int], None] = None) -> WorktreeSession:
        """Create a new worktree session for issue processing"""
        
        if job_id in self.active_sessions:
            raise WorktreeManagerError(f"Session already exists for job {job_id}", job_id)
        
        if len(self.active_sessions) >= self.max_concurrent_sessions:
            raise WorktreeManagerError(
                f"Maximum concurrent sessions reached ({self.max_concurrent_sessions})",
                job_id
            )
        
        session = WorktreeSession(
            job_id=job_id,
            repository=repository,
            issue_number=issue_number,
            status=WorktreeStatus.CREATING,
            progress_callback=progress_callback
        )
        
        self.active_sessions[job_id] = session
        
        try:
            if progress_callback:
                progress_callback("Creating isolated git worktree...", 10)
            
            # Create the git worktree
            worktree_info = self.git_service.create_worktree(
                job_id=job_id,
                repository=repository,
                issue_number=issue_number
            )
            
            session.worktree_info = worktree_info
            session.status = WorktreeStatus.READY
            
            if progress_callback:
                progress_callback("Worktree created successfully", 20)
            
            # Schedule automatic cleanup
            if self.auto_cleanup_enabled:
                self._schedule_cleanup(job_id)
            
            logger.info(
                "Worktree session created",
                job_id=job_id,
                repository=repository,
                issue_number=issue_number,
                worktree_path=str(worktree_info.path)
            )
            
            return session
            
        except GitServiceError as e:
            session.status = WorktreeStatus.FAILED
            session.error_message = f"Git service error: {str(e)}"
            logger.error("Failed to create worktree session", job_id=job_id, error=str(e))
            raise WorktreeManagerError(f"Failed to create worktree: {str(e)}", job_id, session)
        
        except Exception as e:
            session.status = WorktreeStatus.FAILED
            session.error_message = f"Unexpected error: {str(e)}"
            logger.error("Unexpected error creating worktree session", job_id=job_id, error=str(e))
            raise WorktreeManagerError(f"Unexpected error: {str(e)}", job_id, session)

    async def process_with_claude(self,
                                job_id: str,
                                prompt: str,
                                file_paths: List[str] = None,
                                timeout: int = None) -> ClaudeExecutionResult:
        """Process the worktree contents using Claude Code CLI"""
        
        if job_id not in self.active_sessions:
            raise WorktreeManagerError(f"No active session for job {job_id}", job_id)
        
        session = self.active_sessions[job_id]
        
        if session.status != WorktreeStatus.READY:
            raise WorktreeManagerError(
                f"Session not ready for processing (status: {session.status})",
                job_id, session
            )
        
        try:
            session.status = WorktreeStatus.PROCESSING
            session.started_processing_at = datetime.now()
            
            if session.progress_callback:
                session.progress_callback("Starting Claude Code CLI analysis...", 30)
            
            working_directory = str(session.worktree_info.path)
            execution_id = f"{job_id}_claude"
            
            # Execute Claude CLI
            if file_paths:
                result = await self.claude_service.execute_with_files(
                    prompt=prompt,
                    file_paths=file_paths,
                    working_directory=working_directory,
                    execution_id=execution_id,
                    timeout=timeout
                )
            else:
                result = await self.claude_service.execute_interactive(
                    prompt=prompt,
                    working_directory=working_directory,
                    execution_id=execution_id,
                    timeout=timeout
                )
            
            session.claude_results.append(result)
            
            if session.progress_callback:
                if result.status.value == "completed":
                    session.progress_callback("Claude analysis completed successfully", 60)
                else:
                    session.progress_callback(f"Claude analysis {result.status}", 50)
            
            logger.info(
                "Claude processing completed",
                job_id=job_id,
                status=result.status,
                execution_time=result.execution_time,
                stdout_length=len(result.stdout)
            )
            
            return result
            
        except ClaudeCodeServiceError as e:
            session.status = WorktreeStatus.FAILED
            session.error_message = f"Claude service error: {str(e)}"
            logger.error("Claude processing failed", job_id=job_id, error=str(e))
            raise WorktreeManagerError(f"Claude processing failed: {str(e)}", job_id, session)
        
        except Exception as e:
            session.status = WorktreeStatus.FAILED
            session.error_message = f"Unexpected error during processing: {str(e)}"
            logger.error("Unexpected error during Claude processing", job_id=job_id, error=str(e))
            raise WorktreeManagerError(f"Unexpected processing error: {str(e)}", job_id, session)

    async def commit_changes(self,
                           job_id: str,
                           commit_message: str,
                           author_name: str = "Agent",
                           author_email: str = "agent@example.com") -> Optional[str]:
        """Commit changes made in the worktree"""
        
        if job_id not in self.active_sessions:
            raise WorktreeManagerError(f"No active session for job {job_id}", job_id)
        
        session = self.active_sessions[job_id]
        
        try:
            # Get files before and after for tracking
            files_before = set(self.git_service.list_files(job_id))
            
            commit_hash = self.git_service.commit_changes(
                job_id=job_id,
                message=commit_message,
                author_name=author_name,
                author_email=author_email
            )
            
            if commit_hash:
                session.commits_made.append(commit_hash)
                
                # Track file changes
                files_after = set(self.git_service.list_files(job_id))
                session.files_created.extend(list(files_after - files_before))
                
                if session.progress_callback:
                    session.progress_callback("Changes committed successfully", 80)
                
                logger.info(
                    "Changes committed",
                    job_id=job_id,
                    commit_hash=commit_hash[:8],
                    files_changed=len(files_after - files_before)
                )
            
            return commit_hash
            
        except Exception as e:
            session.error_message = f"Commit failed: {str(e)}"
            logger.error("Failed to commit changes", job_id=job_id, error=str(e))
            raise WorktreeManagerError(f"Commit failed: {str(e)}", job_id, session)

    async def complete_session(self, job_id: str) -> WorktreeSession:
        """Mark session as completed and prepare for cleanup"""
        
        if job_id not in self.active_sessions:
            raise WorktreeManagerError(f"No active session for job {job_id}", job_id)
        
        session = self.active_sessions[job_id]
        session.status = WorktreeStatus.COMPLETED
        session.completed_at = datetime.now()
        
        if session.progress_callback:
            session.progress_callback("Session completed successfully", 100)
        
        logger.info(
            "Session completed",
            job_id=job_id,
            duration=(session.completed_at - session.created_at).total_seconds(),
            commits_made=len(session.commits_made),
            files_created=len(session.files_created)
        )
        
        return session

    async def cleanup_session(self, job_id: str, force: bool = False) -> bool:
        """Clean up worktree and remove session"""
        
        if job_id not in self.active_sessions:
            logger.warning("No session found for cleanup", job_id=job_id)
            return False
        
        session = self.active_sessions[job_id]
        
        # Don't cleanup active processing sessions unless forced
        if session.status == WorktreeStatus.PROCESSING and not force:
            logger.warning("Cannot cleanup active processing session", job_id=job_id)
            return False
        
        try:
            session.status = WorktreeStatus.CLEANUP
            
            # Cancel any scheduled cleanup tasks
            if job_id in self.cleanup_tasks:
                self.cleanup_tasks[job_id].cancel()
                del self.cleanup_tasks[job_id]
            
            # Cleanup git worktree
            cleanup_success = self.git_service.cleanup_worktree(job_id)
            
            # Remove session
            session.status = WorktreeStatus.DESTROYED
            del self.active_sessions[job_id]
            
            logger.info(
                "Session cleaned up",
                job_id=job_id,
                git_cleanup_success=cleanup_success,
                force=force
            )
            
            return cleanup_success
            
        except Exception as e:
            logger.error("Failed to cleanup session", job_id=job_id, error=str(e))
            return False

    async def get_session_info(self, job_id: str) -> Optional[WorktreeSession]:
        """Get information about a specific session"""
        return self.active_sessions.get(job_id)

    async def list_active_sessions(self) -> List[WorktreeSession]:
        """List all active sessions"""
        return list(self.active_sessions.values())

    async def get_session_files(self, job_id: str, pattern: str = "**/*") -> List[str]:
        """Get list of files in a session's worktree"""
        if job_id not in self.active_sessions:
            return []
        return self.git_service.list_files(job_id, pattern)

    async def get_file_content(self, job_id: str, file_path: str) -> Optional[str]:
        """Get content of a file from session's worktree"""
        if job_id not in self.active_sessions:
            return None
        return self.git_service.get_file_content(job_id, file_path)

    async def health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check"""
        try:
            # Check git service
            git_info = self.git_service.get_repository_info()
            git_stats = self.git_service.get_worktree_stats()
            
            # Check Claude service
            claude_health = await self.claude_service.health_check()
            claude_stats = self.claude_service.get_service_stats()
            
            # Manager stats
            active_sessions = len(self.active_sessions)
            processing_sessions = sum(1 for s in self.active_sessions.values() 
                                    if s.status == WorktreeStatus.PROCESSING)
            
            return {
                "healthy": git_info and claude_health.get("healthy", False),
                "active_sessions": active_sessions,
                "processing_sessions": processing_sessions,
                "max_concurrent_sessions": self.max_concurrent_sessions,
                "git_service": {
                    "repository_info": git_info,
                    "worktree_stats": git_stats
                },
                "claude_service": {
                    "health": claude_health,
                    "stats": claude_stats
                },
                "sessions": [
                    {
                        "job_id": session.job_id,
                        "status": session.status,
                        "repository": session.repository,
                        "issue_number": session.issue_number,
                        "created_at": session.created_at.isoformat(),
                        "duration_seconds": (datetime.now() - session.created_at).total_seconds()
                    }
                    for session in self.active_sessions.values()
                ]
            }
            
        except Exception as e:
            logger.error("Health check failed", error=str(e))
            return {
                "healthy": False,
                "error": str(e),
                "active_sessions": len(self.active_sessions),
                "processing_sessions": 0
            }

    def _schedule_cleanup(self, job_id: str) -> None:
        """Schedule automatic cleanup for a session"""
        async def cleanup_after_timeout():
            try:
                await asyncio.sleep(self.session_timeout.total_seconds())
                await self.cleanup_session(job_id, force=True)
                logger.info("Automatic cleanup completed", job_id=job_id)
            except Exception as e:
                logger.error("Automatic cleanup failed", job_id=job_id, error=str(e))
        
        task = asyncio.create_task(cleanup_after_timeout())
        self.cleanup_tasks[job_id] = task

    async def shutdown(self) -> Dict[str, bool]:
        """Gracefully shutdown the worktree manager"""
        logger.info("Shutting down worktree manager", active_sessions=len(self.active_sessions))
        
        # Cancel all cleanup tasks
        for task in self.cleanup_tasks.values():
            task.cancel()
        self.cleanup_tasks.clear()
        
        # Cleanup all active sessions
        cleanup_results = {}
        for job_id in list(self.active_sessions.keys()):
            cleanup_results[job_id] = await self.cleanup_session(job_id, force=True)
        
        logger.info("Worktree manager shutdown completed", cleanup_results=cleanup_results)
        return cleanup_results