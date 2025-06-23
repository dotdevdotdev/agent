"""
Tests for Claude Code Service
"""

import pytest
import asyncio
import tempfile
import os
from unittest.mock import patch, AsyncMock, MagicMock
from pathlib import Path

from src.services.claude_code_service import (
    ClaudeCodeService, ClaudeCodeServiceError, ClaudeExecutionResult,
    ClaudeProcessStatus, ClaudeError
)

# Enable async test support
pytest_plugins = ('pytest_asyncio',)


class TestClaudeCodeService:
    """Test cases for ClaudeCodeService"""

    def test_initialization_with_invalid_cli(self):
        """Test service initialization with invalid CLI path"""
        with pytest.raises(ClaudeCodeServiceError, match="Claude CLI not found"):
            ClaudeCodeService(cli_path="/nonexistent/claude")

    @patch('subprocess.run')
    def test_initialization_success(self, mock_run):
        """Test successful service initialization"""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "claude-cli version 1.0.0"
        
        service = ClaudeCodeService(cli_path="claude")
        assert service.cli_path == "claude"
        assert len(service.execution_history) == 0

    @patch('subprocess.run')
    def test_validation_cli_failure(self, mock_run):
        """Test CLI validation failure"""
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "Command failed"
        
        with pytest.raises(ClaudeCodeServiceError, match="Claude CLI version check failed"):
            ClaudeCodeService(cli_path="claude")

    @patch('subprocess.run')
    @pytest.mark.asyncio
    async def test_execute_interactive_success(self, mock_run):
        """Test successful interactive execution"""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "claude-cli version 1.0.0"
        
        with tempfile.TemporaryDirectory() as temp_dir:
            service = ClaudeCodeService(cli_path="claude")
            
            # Mock the async subprocess
            with patch('asyncio.create_subprocess_exec') as mock_subprocess:
                mock_process = AsyncMock()
                mock_process.communicate.return_value = (
                    b"Analysis complete: Code looks good!",
                    b""
                )
                mock_process.returncode = 0
                mock_subprocess.return_value = mock_process
                
                result = await service.execute_interactive(
                    "Analyze this code",
                    temp_dir,
                    execution_id="test-001"
                )
                
                assert result.status == ClaudeProcessStatus.COMPLETED
                assert result.return_code == 0
                assert "Analysis complete" in result.stdout
                assert result.execution_time > 0

    @patch('subprocess.run')
    @pytest.mark.asyncio
    async def test_execute_interactive_timeout(self, mock_run):
        """Test execution timeout handling"""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "claude-cli version 1.0.0"
        
        with tempfile.TemporaryDirectory() as temp_dir:
            service = ClaudeCodeService(cli_path="claude")
            
            # Mock the async subprocess to timeout
            with patch('asyncio.create_subprocess_exec') as mock_subprocess:
                mock_process = AsyncMock()
                mock_process.communicate.side_effect = asyncio.TimeoutError()
                mock_process.terminate = AsyncMock()
                mock_process.wait = AsyncMock()
                mock_subprocess.return_value = mock_process
                
                result = await service.execute_interactive(
                    "Long running task",
                    temp_dir,
                    timeout=1  # 1 second timeout
                )
                
                assert result.status == ClaudeProcessStatus.TIMEOUT
                assert result.error_type == ClaudeError.TIMEOUT
                assert "timed out" in result.error_message

    @patch('subprocess.run')
    @pytest.mark.asyncio
    async def test_execute_with_files(self, mock_run):
        """Test execution with specific files"""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "claude-cli version 1.0.0"
        
        with tempfile.TemporaryDirectory() as temp_dir:
            service = ClaudeCodeService(cli_path="claude")
            
            # Create test files
            test_file = Path(temp_dir) / "test.py"
            test_file.write_text("print('hello')")
            
            with patch('asyncio.create_subprocess_exec') as mock_subprocess:
                mock_process = AsyncMock()
                mock_process.communicate.return_value = (
                    b"File analysis complete",
                    b""
                )
                mock_process.returncode = 0
                mock_subprocess.return_value = mock_process
                
                result = await service.execute_with_files(
                    "Analyze these files",
                    ["test.py"],
                    temp_dir
                )
                
                assert result.status == ClaudeProcessStatus.COMPLETED
                # Check that the service executed successfully
                assert result.return_code == 0

    @patch('subprocess.run')
    @pytest.mark.asyncio
    async def test_cancel_execution(self, mock_run):
        """Test execution cancellation"""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "claude-cli version 1.0.0"
        
        service = ClaudeCodeService(cli_path="claude")
        
        # Mock an active process
        mock_process = AsyncMock()
        mock_process.terminate = AsyncMock()
        mock_process.wait = AsyncMock()
        service.active_processes["test-exec"] = mock_process
        
        result = await service.cancel_execution("test-exec")
        
        assert result is True
        assert "test-exec" not in service.active_processes
        mock_process.terminate.assert_called_once()

    @patch('subprocess.run')
    def test_get_service_stats(self, mock_run):
        """Test service statistics calculation"""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "claude-cli version 1.0.0"
        
        service = ClaudeCodeService(cli_path="claude")
        
        # Add some mock execution history
        service.execution_history.extend([
            ClaudeExecutionResult(
                status=ClaudeProcessStatus.COMPLETED,
                execution_time=1.5
            ),
            ClaudeExecutionResult(
                status=ClaudeProcessStatus.FAILED,
                execution_time=0.8
            )
        ])
        
        stats = service.get_service_stats()
        
        assert stats["total_executions"] == 2
        assert stats["successful_executions"] == 1
        assert stats["failed_executions"] == 1
        assert stats["success_rate"] == 0.5
        assert stats["average_execution_time"] == 1.15

    @patch('subprocess.run')
    def test_error_classification(self, mock_run):
        """Test error classification logic"""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "claude-cli version 1.0.0"
        
        service = ClaudeCodeService(cli_path="claude")
        
        # Test different error types
        test_cases = [
            (127, "", ClaudeError.COMMAND_NOT_FOUND),
            (1, "authentication failed", ClaudeError.AUTHENTICATION_ERROR),
            (1, "quota exceeded", ClaudeError.QUOTA_EXCEEDED),
            (1, "network error", ClaudeError.NETWORK_ERROR),
            (1, "out of memory", ClaudeError.MEMORY_ERROR),
            (1, "invalid argument", ClaudeError.INVALID_ARGUMENTS),
            (1, "parse error", ClaudeError.PARSING_ERROR),
            (1, "unknown issue", ClaudeError.UNKNOWN_ERROR)
        ]
        
        for return_code, stderr, expected_error in test_cases:
            result = ClaudeExecutionResult(
                status=ClaudeProcessStatus.FAILED,
                return_code=return_code,
                stderr=stderr
            )
            error_type = service._classify_error(result)
            assert error_type == expected_error

    @patch('subprocess.run')
    @pytest.mark.asyncio
    async def test_health_check_success(self, mock_run):
        """Test health check with healthy service"""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "claude-cli version 1.0.0"
        
        service = ClaudeCodeService(cli_path="claude")
        
        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.communicate.return_value = (b"claude-cli version 1.0.0", b"")
            mock_process.returncode = 0
            mock_subprocess.return_value = mock_process
            
            health = await service.health_check()
            
            assert health["healthy"] is True
            assert health["version_check_passed"] is True
            assert "claude-cli version" in health["version_output"]

    @patch('subprocess.run')
    @pytest.mark.asyncio
    async def test_health_check_failure(self, mock_run):
        """Test health check with unhealthy service"""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "claude-cli version 1.0.0"
        
        service = ClaudeCodeService(cli_path="claude")
        
        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            mock_subprocess.side_effect = Exception("CLI not available")
            
            health = await service.health_check()
            
            assert health["healthy"] is False
            assert "CLI not available" in health["error"]


if __name__ == "__main__":
    pytest.main([__file__])