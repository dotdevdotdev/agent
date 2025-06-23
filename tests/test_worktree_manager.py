"""
Tests for Worktree Manager
"""

import pytest
import asyncio
import tempfile
from unittest.mock import patch, AsyncMock, MagicMock
from pathlib import Path
from datetime import datetime

from src.services.worktree_manager import (
    WorktreeManager, WorktreeSession, WorktreeStatus, WorktreeManagerError
)
from src.services.git_service import GitService, WorktreeInfo
from src.services.claude_code_service import (
    ClaudeCodeService, ClaudeExecutionResult, ClaudeProcessStatus
)

# Enable async test support
pytest_plugins = ('pytest_asyncio',)


class TestWorktreeManager:
    """Test cases for WorktreeManager"""

    @pytest.fixture
    def mock_git_service(self):
        """Mock git service"""
        git_service = MagicMock(spec=GitService)
        git_service.create_worktree.return_value = WorktreeInfo(
            path=Path("/tmp/worktree"),
            branch="test-branch",
            commit_hash="abc123",
            created_at=datetime.now(),
            job_id="test-job",
            repository="test/repo",
            issue_number=1
        )
        git_service.cleanup_worktree.return_value = True
        git_service.get_repository_info.return_value = {"current_branch": "master"}
        git_service.get_worktree_stats.return_value = {"active_worktrees": 0}
        git_service.list_files.return_value = ["file1.py", "file2.md"]
        git_service.commit_changes.return_value = "def456"
        return git_service

    @pytest.fixture
    def mock_claude_service(self):
        """Mock Claude service"""
        claude_service = MagicMock(spec=ClaudeCodeService)
        claude_service.health_check = AsyncMock(return_value={"healthy": True})
        claude_service.get_service_stats.return_value = {"total_executions": 0}
        claude_service.execute_interactive = AsyncMock(return_value=ClaudeExecutionResult(
            status=ClaudeProcessStatus.COMPLETED,
            stdout="Analysis complete",
            execution_time=1.5
        ))
        claude_service.execute_with_files = AsyncMock(return_value=ClaudeExecutionResult(
            status=ClaudeProcessStatus.COMPLETED,
            stdout="File analysis complete",
            execution_time=2.0
        ))
        return claude_service

    def test_initialization(self, mock_git_service, mock_claude_service):
        """Test worktree manager initialization"""
        manager = WorktreeManager(
            git_service=mock_git_service,
            claude_service=mock_claude_service
        )
        
        assert manager.git_service == mock_git_service
        assert manager.claude_service == mock_claude_service
        assert len(manager.active_sessions) == 0
        assert manager.max_concurrent_sessions > 0

    @pytest.mark.asyncio
    async def test_create_session_success(self, mock_git_service, mock_claude_service):
        """Test successful session creation"""
        manager = WorktreeManager(
            git_service=mock_git_service,
            claude_service=mock_claude_service
        )
        
        progress_calls = []
        def progress_callback(message, progress):
            progress_calls.append((message, progress))
        
        session = await manager.create_session(
            job_id="test-job-001",
            repository="test/repo",
            issue_number=123,
            progress_callback=progress_callback
        )
        
        assert session.job_id == "test-job-001"
        assert session.repository == "test/repo"
        assert session.issue_number == 123
        assert session.status == WorktreeStatus.READY
        assert session.worktree_info is not None
        assert len(progress_calls) == 2  # Progress updates called
        
        # Check session is tracked
        assert "test-job-001" in manager.active_sessions

    @pytest.mark.asyncio
    async def test_create_session_duplicate(self, mock_git_service, mock_claude_service):
        """Test creation of duplicate session fails"""
        manager = WorktreeManager(
            git_service=mock_git_service,
            claude_service=mock_claude_service
        )
        
        # Create first session
        await manager.create_session("test-job", "test/repo", 1)
        
        # Try to create duplicate
        with pytest.raises(WorktreeManagerError, match="Session already exists"):
            await manager.create_session("test-job", "test/repo", 2)

    @pytest.mark.asyncio
    async def test_create_session_max_concurrent(self, mock_git_service, mock_claude_service):
        """Test maximum concurrent sessions limit"""
        manager = WorktreeManager(
            git_service=mock_git_service,
            claude_service=mock_claude_service
        )
        manager.max_concurrent_sessions = 2
        
        # Create max sessions
        await manager.create_session("job-1", "test/repo", 1)
        await manager.create_session("job-2", "test/repo", 2)
        
        # Try to create one more
        with pytest.raises(WorktreeManagerError, match="Maximum concurrent sessions"):
            await manager.create_session("job-3", "test/repo", 3)

    @pytest.mark.asyncio
    async def test_process_with_claude_interactive(self, mock_git_service, mock_claude_service):
        """Test Claude processing in interactive mode"""
        manager = WorktreeManager(
            git_service=mock_git_service,
            claude_service=mock_claude_service
        )
        
        # Create session
        session = await manager.create_session("test-job", "test/repo", 1)
        
        # Process with Claude
        result = await manager.process_with_claude(
            job_id="test-job",
            prompt="Analyze this code"
        )
        
        assert result.status == ClaudeProcessStatus.COMPLETED
        assert "Analysis complete" in result.stdout
        assert len(session.claude_results) == 1
        
        # Verify Claude service was called correctly
        mock_claude_service.execute_interactive.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_with_claude_with_files(self, mock_git_service, mock_claude_service):
        """Test Claude processing with specific files"""
        manager = WorktreeManager(
            git_service=mock_git_service,
            claude_service=mock_claude_service
        )
        
        # Create session
        await manager.create_session("test-job", "test/repo", 1)
        
        # Process with files
        result = await manager.process_with_claude(
            job_id="test-job",
            prompt="Analyze these files",
            file_paths=["file1.py", "file2.py"]
        )
        
        assert result.status == ClaudeProcessStatus.COMPLETED
        
        # Verify correct method was called
        mock_claude_service.execute_with_files.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_without_session(self, mock_git_service, mock_claude_service):
        """Test processing without creating session first"""
        manager = WorktreeManager(
            git_service=mock_git_service,
            claude_service=mock_claude_service
        )
        
        with pytest.raises(WorktreeManagerError, match="No active session"):
            await manager.process_with_claude("nonexistent-job", "prompt")

    @pytest.mark.asyncio
    async def test_commit_changes(self, mock_git_service, mock_claude_service):
        """Test committing changes in worktree"""
        manager = WorktreeManager(
            git_service=mock_git_service,
            claude_service=mock_claude_service
        )
        
        # Create session
        session = await manager.create_session("test-job", "test/repo", 1)
        
        # Commit changes
        commit_hash = await manager.commit_changes(
            job_id="test-job",
            commit_message="Test commit",
            author_name="Test Author"
        )
        
        assert commit_hash == "def456"
        assert len(session.commits_made) == 1
        assert "def456" in session.commits_made

    @pytest.mark.asyncio
    async def test_complete_session(self, mock_git_service, mock_claude_service):
        """Test session completion"""
        manager = WorktreeManager(
            git_service=mock_git_service,
            claude_service=mock_claude_service
        )
        
        # Create session
        session = await manager.create_session("test-job", "test/repo", 1)
        
        # Complete session
        completed_session = await manager.complete_session("test-job")
        
        assert completed_session.status == WorktreeStatus.COMPLETED
        assert completed_session.completed_at is not None

    @pytest.mark.asyncio
    async def test_cleanup_session(self, mock_git_service, mock_claude_service):
        """Test session cleanup"""
        manager = WorktreeManager(
            git_service=mock_git_service,
            claude_service=mock_claude_service
        )
        manager.auto_cleanup_enabled = False  # Disable auto cleanup for test
        
        # Create session
        await manager.create_session("test-job", "test/repo", 1)
        assert "test-job" in manager.active_sessions
        
        # Cleanup session
        result = await manager.cleanup_session("test-job")
        
        assert result is True
        assert "test-job" not in manager.active_sessions
        mock_git_service.cleanup_worktree.assert_called_once_with("test-job")

    @pytest.mark.asyncio
    async def test_list_active_sessions(self, mock_git_service, mock_claude_service):
        """Test listing active sessions"""
        manager = WorktreeManager(
            git_service=mock_git_service,
            claude_service=mock_claude_service
        )
        
        # Create multiple sessions
        await manager.create_session("job-1", "test/repo", 1)
        await manager.create_session("job-2", "test/repo", 2)
        
        sessions = await manager.list_active_sessions()
        
        assert len(sessions) == 2
        job_ids = [s.job_id for s in sessions]
        assert "job-1" in job_ids
        assert "job-2" in job_ids

    @pytest.mark.asyncio
    async def test_get_session_files(self, mock_git_service, mock_claude_service):
        """Test getting session files"""
        manager = WorktreeManager(
            git_service=mock_git_service,
            claude_service=mock_claude_service
        )
        
        # Create session
        await manager.create_session("test-job", "test/repo", 1)
        
        # Get files
        files = await manager.get_session_files("test-job")
        
        assert files == ["file1.py", "file2.md"]
        mock_git_service.list_files.assert_called_with("test-job", "**/*")

    @pytest.mark.asyncio
    async def test_health_check(self, mock_git_service, mock_claude_service):
        """Test health check functionality"""
        manager = WorktreeManager(
            git_service=mock_git_service,
            claude_service=mock_claude_service
        )
        
        # Create a session
        await manager.create_session("test-job", "test/repo", 1)
        
        health = await manager.health_check()
        
        assert health["healthy"] is True
        assert health["active_sessions"] == 1
        assert health["processing_sessions"] == 0
        assert "git_service" in health
        assert "claude_service" in health
        assert len(health["sessions"]) == 1

    @pytest.mark.asyncio
    async def test_shutdown(self, mock_git_service, mock_claude_service):
        """Test graceful shutdown"""
        manager = WorktreeManager(
            git_service=mock_git_service,
            claude_service=mock_claude_service
        )
        manager.auto_cleanup_enabled = False  # Disable auto cleanup for test
        
        # Create sessions
        await manager.create_session("job-1", "test/repo", 1)
        await manager.create_session("job-2", "test/repo", 2)
        
        # Shutdown
        results = await manager.shutdown()
        
        assert len(results) == 2
        assert results["job-1"] is True
        assert results["job-2"] is True
        assert len(manager.active_sessions) == 0


if __name__ == "__main__":
    pytest.main([__file__])