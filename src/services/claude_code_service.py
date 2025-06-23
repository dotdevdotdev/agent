"""
Claude Code CLI service wrapper with comprehensive error handling
"""

import asyncio
import json
import os
import signal
import structlog
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from config.settings import settings

logger = structlog.get_logger()


class ClaudeProcessStatus(str, Enum):
    """Status of Claude CLI process"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ClaudeError(str, Enum):
    """Types of Claude CLI errors"""
    COMMAND_NOT_FOUND = "command_not_found"
    INVALID_ARGUMENTS = "invalid_arguments"
    PERMISSION_DENIED = "permission_denied"
    TIMEOUT = "timeout"
    MEMORY_ERROR = "memory_error"
    NETWORK_ERROR = "network_error"
    AUTHENTICATION_ERROR = "authentication_error"
    QUOTA_EXCEEDED = "quota_exceeded"
    PARSING_ERROR = "parsing_error"
    UNKNOWN_ERROR = "unknown_error"


@dataclass
class ClaudeExecutionResult:
    """Result of Claude CLI execution"""
    status: ClaudeProcessStatus
    stdout: str = ""
    stderr: str = ""
    return_code: int = 0
    execution_time: float = 0.0
    error_type: Optional[ClaudeError] = None
    error_message: str = ""
    command: List[str] = field(default_factory=list)
    working_directory: str = ""
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    memory_usage_mb: float = 0.0
    cpu_usage_percent: float = 0.0


class ClaudeCodeServiceError(Exception):
    """Custom exception for Claude Code service errors"""
    def __init__(self, message: str, error_type: ClaudeError = ClaudeError.UNKNOWN_ERROR, 
                 result: ClaudeExecutionResult = None):
        self.message = message
        self.error_type = error_type
        self.result = result
        super().__init__(message)


class ClaudeCodeService:
    """Service for executing Claude Code CLI with comprehensive error handling"""

    def __init__(self, cli_path: str = None, timeout: int = None):
        self.cli_path = cli_path or settings.CLAUDE_CODE_PATH
        self.default_timeout = timeout or settings.CLAUDE_TIMEOUT
        self.active_processes: Dict[str, subprocess.Popen] = {}
        self.execution_history: List[ClaudeExecutionResult] = []
        
        # Validate CLI availability on initialization
        self._validate_cli_availability()

    def _validate_cli_availability(self) -> None:
        """Validate that Claude CLI is available and working"""
        try:
            result = subprocess.run(
                [self.cli_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                raise ClaudeCodeServiceError(
                    f"Claude CLI version check failed: {result.stderr}",
                    ClaudeError.COMMAND_NOT_FOUND
                )
            logger.info("Claude CLI validated", version_output=result.stdout.strip())
        except FileNotFoundError:
            raise ClaudeCodeServiceError(
                f"Claude CLI not found at path: {self.cli_path}",
                ClaudeError.COMMAND_NOT_FOUND
            )
        except subprocess.TimeoutExpired:
            raise ClaudeCodeServiceError(
                "Claude CLI version check timed out",
                ClaudeError.TIMEOUT
            )

    async def execute_interactive(self, 
                                prompt: str,
                                working_directory: str,
                                execution_id: str = None,
                                timeout: int = None,
                                progress_callback: Callable[[str], None] = None) -> ClaudeExecutionResult:
        """Execute Claude CLI in interactive mode with a prompt"""
        
        execution_id = execution_id or f"exec_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        timeout = timeout or self.default_timeout
        
        result = ClaudeExecutionResult(
            status=ClaudeProcessStatus.PENDING,
            command=[self.cli_path],
            working_directory=working_directory,
            started_at=datetime.now()
        )
        
        try:
            # Validate working directory
            if not os.path.isdir(working_directory):
                raise ClaudeCodeServiceError(
                    f"Working directory does not exist: {working_directory}",
                    ClaudeError.INVALID_ARGUMENTS
                )
            
            # Create temporary file for prompt if it's very long
            prompt_file = None
            if len(prompt) > 10000:  # Large prompt, use file
                prompt_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.md')
                prompt_file.write(prompt)
                prompt_file.close()
                command = [self.cli_path, "--file", prompt_file.name]
            else:
                command = [self.cli_path]
            
            result.command = command
            result.status = ClaudeProcessStatus.RUNNING
            
            logger.info(
                "Starting Claude CLI execution",
                execution_id=execution_id,
                working_dir=working_directory,
                prompt_length=len(prompt),
                timeout=timeout
            )
            
            # Start process
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_directory,
                env=dict(os.environ, CLAUDE_CLI_MODE="agent")
            )
            
            self.active_processes[execution_id] = process
            
            # Send prompt if not using file
            stdin_data = None if prompt_file else prompt.encode('utf-8')
            
            try:
                # Execute with timeout
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(input=stdin_data),
                    timeout=timeout
                )
                
                result.stdout = stdout.decode('utf-8', errors='replace')
                result.stderr = stderr.decode('utf-8', errors='replace')
                result.return_code = process.returncode
                result.completed_at = datetime.now()
                result.execution_time = (result.completed_at - result.started_at).total_seconds()
                
                # Determine status based on return code
                if result.return_code == 0:
                    result.status = ClaudeProcessStatus.COMPLETED
                else:
                    result.status = ClaudeProcessStatus.FAILED
                    result.error_type = self._classify_error(result)
                    result.error_message = self._extract_error_message(result)
                
            except asyncio.TimeoutError:
                result.status = ClaudeProcessStatus.TIMEOUT
                result.error_type = ClaudeError.TIMEOUT
                result.error_message = f"Execution timed out after {timeout} seconds"
                result.completed_at = datetime.now()
                result.execution_time = timeout
                
                # Terminate the process
                try:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                
            finally:
                # Cleanup
                if execution_id in self.active_processes:
                    del self.active_processes[execution_id]
                if prompt_file:
                    try:
                        os.unlink(prompt_file.name)
                    except OSError:
                        pass
                
                # Report progress
                if progress_callback:
                    progress_callback(f"Claude CLI execution {result.status}")
            
            # Store execution history
            self.execution_history.append(result)
            
            # Log completion
            logger.info(
                "Claude CLI execution completed",
                execution_id=execution_id,
                status=result.status,
                return_code=result.return_code,
                execution_time=result.execution_time,
                stdout_length=len(result.stdout),
                stderr_length=len(result.stderr)
            )
            
            return result
            
        except Exception as e:
            result.status = ClaudeProcessStatus.FAILED
            result.error_type = ClaudeError.UNKNOWN_ERROR
            result.error_message = str(e)
            result.completed_at = datetime.now()
            result.execution_time = (result.completed_at - result.started_at).total_seconds()
            
            logger.error(
                "Claude CLI execution failed",
                execution_id=execution_id,
                error=str(e),
                error_type=result.error_type
            )
            
            self.execution_history.append(result)
            raise ClaudeCodeServiceError(
                f"Claude CLI execution failed: {str(e)}",
                result.error_type,
                result
            )

    async def execute_with_files(self,
                                prompt: str,
                                file_paths: List[str],
                                working_directory: str,
                                execution_id: str = None,
                                timeout: int = None) -> ClaudeExecutionResult:
        """Execute Claude CLI with specific files included"""
        
        # Build command with file arguments
        command = [self.cli_path]
        for file_path in file_paths:
            command.extend(["--include", file_path])
        
        # Create enhanced prompt that mentions the files
        enhanced_prompt = f"""Files to analyze: {', '.join(file_paths)}

{prompt}

Please focus your analysis on the specified files."""
        
        return await self.execute_interactive(
            enhanced_prompt,
            working_directory,
            execution_id,
            timeout
        )

    async def cancel_execution(self, execution_id: str) -> bool:
        """Cancel a running Claude CLI execution"""
        if execution_id not in self.active_processes:
            return False
        
        try:
            process = self.active_processes[execution_id]
            process.terminate()
            
            # Wait for graceful termination
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
            
            del self.active_processes[execution_id]
            
            logger.info("Claude CLI execution cancelled", execution_id=execution_id)
            return True
            
        except Exception as e:
            logger.error("Failed to cancel Claude CLI execution", execution_id=execution_id, error=str(e))
            return False

    def get_active_executions(self) -> List[str]:
        """Get list of active execution IDs"""
        return list(self.active_processes.keys())

    def get_execution_history(self, limit: int = 100) -> List[ClaudeExecutionResult]:
        """Get recent execution history"""
        return self.execution_history[-limit:]

    def get_service_stats(self) -> Dict[str, Any]:
        """Get service statistics"""
        total_executions = len(self.execution_history)
        successful_executions = sum(1 for r in self.execution_history if r.status == ClaudeProcessStatus.COMPLETED)
        failed_executions = sum(1 for r in self.execution_history if r.status == ClaudeProcessStatus.FAILED)
        avg_execution_time = sum(r.execution_time for r in self.execution_history) / max(total_executions, 1)
        
        return {
            "cli_path": self.cli_path,
            "default_timeout": self.default_timeout,
            "active_executions": len(self.active_processes),
            "total_executions": total_executions,
            "successful_executions": successful_executions,
            "failed_executions": failed_executions,
            "success_rate": successful_executions / max(total_executions, 1),
            "average_execution_time": avg_execution_time,
            "active_execution_ids": list(self.active_processes.keys())
        }

    def _classify_error(self, result: ClaudeExecutionResult) -> ClaudeError:
        """Classify error based on return code and stderr content"""
        stderr_lower = result.stderr.lower()
        
        if result.return_code == 127:
            return ClaudeError.COMMAND_NOT_FOUND
        elif result.return_code == 126:
            return ClaudeError.PERMISSION_DENIED
        elif "authentication" in stderr_lower or "unauthorized" in stderr_lower:
            return ClaudeError.AUTHENTICATION_ERROR
        elif "quota" in stderr_lower or "rate limit" in stderr_lower:
            return ClaudeError.QUOTA_EXCEEDED
        elif "network" in stderr_lower or "connection" in stderr_lower:
            return ClaudeError.NETWORK_ERROR
        elif "memory" in stderr_lower or "out of memory" in stderr_lower:
            return ClaudeError.MEMORY_ERROR
        elif "timeout" in stderr_lower:
            return ClaudeError.TIMEOUT
        elif "invalid" in stderr_lower or "argument" in stderr_lower:
            return ClaudeError.INVALID_ARGUMENTS
        elif "parse" in stderr_lower or "syntax" in stderr_lower:
            return ClaudeError.PARSING_ERROR
        else:
            return ClaudeError.UNKNOWN_ERROR

    def _extract_error_message(self, result: ClaudeExecutionResult) -> str:
        """Extract meaningful error message from stderr"""
        if result.stderr:
            lines = result.stderr.strip().split('\n')
            # Return the last non-empty line as it's usually the most relevant
            for line in reversed(lines):
                line = line.strip()
                if line and not line.startswith('Traceback'):
                    return line
            return result.stderr.strip()
        elif result.return_code != 0:
            return f"Process exited with code {result.return_code}"
        else:
            return "Unknown error occurred"

    async def health_check(self) -> Dict[str, Any]:
        """Perform health check of Claude CLI service"""
        try:
            # Quick version check
            result = await asyncio.create_subprocess_exec(
                self.cli_path, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=10)
            
            is_healthy = result.returncode == 0
            
            return {
                "healthy": is_healthy,
                "cli_path": self.cli_path,
                "version_check_passed": is_healthy,
                "version_output": stdout.decode('utf-8').strip() if stdout else "",
                "error_output": stderr.decode('utf-8').strip() if stderr else "",
                "active_executions": len(self.active_processes),
                "total_executions": len(self.execution_history)
            }
            
        except Exception as e:
            return {
                "healthy": False,
                "cli_path": self.cli_path,
                "error": str(e),
                "active_executions": len(self.active_processes),
                "total_executions": len(self.execution_history)
            }