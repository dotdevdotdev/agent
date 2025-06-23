"""
Tests for Processing Orchestrator
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime

from src.services.processing_orchestrator import (
    ProcessingOrchestrator, ProcessingContext, ProcessingStage, ProcessingOrchestratorError
)
from src.services.issue_parser import ParsedTask, TaskType, TaskPriority, OutputFormat
from src.services.worktree_manager import WorktreeManager, WorktreeSession, WorktreeStatus
from src.services.prompt_builder import PromptBuilder, BuiltPrompt, PromptTemplate
from src.services.result_processor import ResultProcessor, ParsedResult, ResultType
from src.services.github_client import GitHubClient

# Enable async test support
pytest_plugins = ('pytest_asyncio',)


class TestProcessingOrchestrator:
    """Test cases for ProcessingOrchestrator"""

    @pytest.fixture
    def mock_worktree_manager(self):
        """Mock worktree manager"""
        manager = MagicMock(spec=WorktreeManager)
        manager.create_session = AsyncMock(return_value=WorktreeSession(
            job_id="test-job",
            repository="test/repo",
            issue_number=123,
            status=WorktreeStatus.READY
        ))
        manager.complete_session = AsyncMock()
        manager.cleanup_session = AsyncMock(return_value=True)
        manager.process_with_claude = AsyncMock()
        manager.health_check = AsyncMock(return_value={"healthy": True})
        return manager

    @pytest.fixture
    def mock_prompt_builder(self):
        """Mock prompt builder"""
        builder = MagicMock(spec=PromptBuilder)
        builder.build_prompt = AsyncMock(return_value=BuiltPrompt(
            prompt="Test prompt",
            template_used=PromptTemplate.CODE_ANALYSIS,
            context_files=["test.py"],
            estimated_tokens=100
        ))
        return builder

    @pytest.fixture
    def mock_result_processor(self):
        """Mock result processor"""
        processor = MagicMock(spec=ResultProcessor)
        processor.process_result = AsyncMock(return_value=ParsedResult(
            result_type=ResultType.CODE_CHANGES,
            summary="Test analysis",
            confidence_score=0.8
        ))
        processor.format_for_github = AsyncMock()
        processor.post_to_github = AsyncMock(return_value={"primary_comment": {"id": 123}})
        return processor

    @pytest.fixture
    def mock_github_client(self):
        """Mock GitHub client"""
        return MagicMock(spec=GitHubClient)

    @pytest.fixture
    def sample_task(self):
        """Sample parsed task"""
        return ParsedTask(
            task_type=TaskType.CODE_ANALYSIS,
            priority=TaskPriority.HIGH,
            prompt="Analyze the code quality",
            relevant_files=["main.py"],
            context="Test context",
            output_format=OutputFormat.ANALYSIS_REPORT,
            estimated_complexity="Medium",
            validation_errors=[],
            raw_issue_body="Test issue body"
        )

    def test_initialization(self, mock_worktree_manager, mock_prompt_builder, 
                           mock_result_processor, mock_github_client):
        """Test orchestrator initialization"""
        orchestrator = ProcessingOrchestrator(
            worktree_manager=mock_worktree_manager,
            prompt_builder=mock_prompt_builder,
            result_processor=mock_result_processor,
            github_client=mock_github_client
        )
        
        assert orchestrator.worktree_manager == mock_worktree_manager
        assert orchestrator.prompt_builder == mock_prompt_builder
        assert orchestrator.result_processor == mock_result_processor
        assert orchestrator.github_client == mock_github_client
        assert len(orchestrator.active_contexts) == 0

    @pytest.mark.asyncio
    async def test_get_processing_status_not_found(self, mock_worktree_manager):
        """Test getting status for non-existent job"""
        orchestrator = ProcessingOrchestrator(worktree_manager=mock_worktree_manager)
        
        status = await orchestrator.get_processing_status("nonexistent")
        assert status is None

    @pytest.mark.asyncio
    async def test_cancel_processing_not_found(self, mock_worktree_manager):
        """Test cancelling non-existent job"""
        orchestrator = ProcessingOrchestrator(worktree_manager=mock_worktree_manager)
        
        result = await orchestrator.cancel_processing("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_health_status(self, mock_worktree_manager, mock_prompt_builder, 
                                mock_result_processor, mock_github_client):
        """Test health status check"""
        orchestrator = ProcessingOrchestrator(
            worktree_manager=mock_worktree_manager,
            prompt_builder=mock_prompt_builder,
            result_processor=mock_result_processor,
            github_client=mock_github_client
        )
        
        health = await orchestrator.get_health_status()
        
        assert "healthy" in health
        assert health["active_processing"] == 0
        assert "components" in health
        assert "worktree_manager" in health["components"]

    def test_determine_output_format_simple(self, mock_worktree_manager):
        """Test output format determination with simple result"""
        orchestrator = ProcessingOrchestrator(worktree_manager=mock_worktree_manager)
        
        simple_result = ParsedResult(
            result_type=ResultType.ANALYSIS_REPORT,
            summary="Test",
            code_changes=[]
        )
        
        format_type = orchestrator._determine_output_format(simple_result)
        assert format_type.value == "markdown_comment"

    def test_determine_output_format_complex(self, mock_worktree_manager):
        """Test output format determination with complex result"""
        orchestrator = ProcessingOrchestrator(worktree_manager=mock_worktree_manager)
        
        from src.services.result_processor import CodeChange
        
        complex_result = ParsedResult(
            result_type=ResultType.CODE_CHANGES,
            summary="Test",
            code_changes=[
                CodeChange("file1.py", new_content="code1"),
                CodeChange("file2.py", new_content="code2"),
                CodeChange("file3.py", new_content="code3")
            ]
        )
        
        format_type = orchestrator._determine_output_format(complex_result)
        assert format_type.value == "threaded_comments"


if __name__ == "__main__":
    pytest.main([__file__])