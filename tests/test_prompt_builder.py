"""
Tests for Prompt Builder
"""

import pytest
from unittest.mock import MagicMock

from src.services.prompt_builder import (
    PromptBuilder, PromptTemplate, PromptContext, BuiltPrompt, PromptBuilderError
)
from src.services.issue_parser import ParsedTask, TaskType, TaskPriority, OutputFormat
from src.services.git_service import GitService

# Enable async test support
pytest_plugins = ('pytest_asyncio',)


class TestPromptBuilder:
    """Test cases for PromptBuilder"""

    @pytest.fixture
    def mock_git_service(self):
        """Mock git service"""
        git_service = MagicMock(spec=GitService)
        git_service.get_file_content.return_value = "print('hello world')"
        git_service.list_files.return_value = ["main.py", "utils.py", "tests/test_main.py"]
        return git_service

    @pytest.fixture
    def sample_task(self):
        """Sample parsed task"""
        return ParsedTask(
            task_type=TaskType.CODE_ANALYSIS,
            priority=TaskPriority.MEDIUM,
            prompt="Please analyze the code quality of this Python project",
            relevant_files=["main.py", "utils.py"],
            context="This is a web application using FastAPI",
            output_format=OutputFormat.ANALYSIS_REPORT,
            estimated_complexity="Medium",
            validation_errors=[],
            raw_issue_body="### Task Type\nCode Analysis\n### Detailed Prompt\nPlease analyze...",
            testing_mode=False
        )

    @pytest.fixture
    def sample_context(self):
        """Sample prompt context"""
        return PromptContext(
            repository_name="test/repo",
            issue_number=123,
            job_id="test-job-001",
            working_directory="/tmp/worktree"
        )

    def test_initialization(self, mock_git_service):
        """Test prompt builder initialization"""
        builder = PromptBuilder(git_service=mock_git_service)
        
        assert builder.git_service == mock_git_service
        assert len(builder.templates) == 7  # All template types
        assert builder.max_prompt_tokens > 0

    def test_template_selection_code_analysis(self, mock_git_service, sample_task):
        """Test template selection for code analysis"""
        builder = PromptBuilder(git_service=mock_git_service)
        
        template = builder._select_template(sample_task)
        assert template == PromptTemplate.CODE_ANALYSIS

    def test_template_selection_testing_mode(self, mock_git_service, sample_task):
        """Test template selection in testing mode"""
        builder = PromptBuilder(git_service=mock_git_service)
        
        sample_task.testing_mode = True
        template = builder._select_template(sample_task)
        assert template == PromptTemplate.GENERAL_ASSISTANCE

    def test_template_selection_feature_implementation(self, mock_git_service):
        """Test template selection for feature implementation"""
        builder = PromptBuilder(git_service=mock_git_service)
        
        task = ParsedTask(
            task_type=TaskType.FEATURE_IMPLEMENTATION,
            priority=TaskPriority.HIGH,
            prompt="Add user authentication",
            relevant_files=[],
            context="",
            output_format=OutputFormat.CODE_CHANGES,
            estimated_complexity="Medium",
            validation_errors=[],
            raw_issue_body="### Task Type\nFeature Implementation\n### Detailed Prompt\nAdd user authentication"
        )
        
        template = builder._select_template(task)
        assert template == PromptTemplate.FEATURE_IMPLEMENTATION

    @pytest.mark.asyncio
    async def test_enrich_context_with_files(self, mock_git_service, sample_task, sample_context):
        """Test context enrichment with file loading"""
        builder = PromptBuilder(git_service=mock_git_service)
        
        enriched = await builder._enrich_context(sample_task, sample_context)
        
        assert len(enriched.file_contents) == 2
        assert "main.py" in enriched.file_contents
        assert "utils.py" in enriched.file_contents
        assert enriched.file_contents["main.py"] == "print('hello world')"

    @pytest.mark.asyncio
    async def test_enrich_context_repository_structure(self, mock_git_service, sample_task, sample_context):
        """Test context enrichment with repository structure"""
        builder = PromptBuilder(git_service=mock_git_service)
        
        enriched = await builder._enrich_context(sample_task, sample_context)
        
        assert len(enriched.repository_structure) == 3
        assert "main.py" in enriched.repository_structure
        assert "tests/test_main.py" in enriched.repository_structure

    def test_format_file_list_empty(self, mock_git_service):
        """Test file list formatting with empty list"""
        builder = PromptBuilder(git_service=mock_git_service)
        
        result = builder._format_file_list([])
        assert "No specific files" in result

    def test_format_file_list_with_files(self, mock_git_service):
        """Test file list formatting with files"""
        builder = PromptBuilder(git_service=mock_git_service)
        
        result = builder._format_file_list(["main.py", "utils.py"])
        assert "main.py" in result
        assert "utils.py" in result
        assert "Files to focus on:" in result

    def test_format_file_contents(self, mock_git_service):
        """Test file contents formatting"""
        builder = PromptBuilder(git_service=mock_git_service)
        
        contents = {
            "main.py": "print('hello')",
            "utils.py": "def helper(): pass"
        }
        
        result = builder._format_file_contents(contents)
        assert "### main.py" in result
        assert "### utils.py" in result
        assert "print('hello')" in result
        assert "def helper(): pass" in result

    def test_format_repository_structure(self, mock_git_service):
        """Test repository structure formatting"""
        builder = PromptBuilder(git_service=mock_git_service)
        
        structure = ["main.py", "utils.py", "tests/test_main.py"]
        
        result = builder._format_repository_structure(structure)
        assert "Repository Structure:" in result
        assert "main.py" in result
        assert "utils.py" in result

    def test_format_repository_structure_truncated(self, mock_git_service):
        """Test repository structure formatting with truncation"""
        builder = PromptBuilder(git_service=mock_git_service)
        
        # Create a large structure
        structure = [f"file_{i}.py" for i in range(60)]
        
        result = builder._format_repository_structure(structure)
        assert "truncated" in result
        assert len(result.split('\n')) < 60  # Should be truncated

    def test_estimate_tokens(self, mock_git_service):
        """Test token estimation"""
        builder = PromptBuilder(git_service=mock_git_service)
        
        text = "This is a test string with some words"
        tokens = builder._estimate_tokens(text)
        
        assert tokens > 0
        assert tokens == len(text) // builder.avg_chars_per_token

    def test_apply_template_code_analysis(self, mock_git_service, sample_task, sample_context):
        """Test template application for code analysis"""
        builder = PromptBuilder(git_service=mock_git_service)
        
        sample_context.file_contents = {"main.py": "print('hello')"}
        
        result = builder._apply_template(
            PromptTemplate.CODE_ANALYSIS,
            sample_task,
            sample_context
        )
        
        assert "Code Analysis Request" in result
        assert sample_task.prompt in result
        assert "test/repo" in result
        assert "123" in result

    def test_apply_template_testing_mode(self, mock_git_service, sample_task, sample_context):
        """Test template application with testing mode"""
        builder = PromptBuilder(git_service=mock_git_service)
        
        sample_task.testing_mode = True
        
        result = builder._apply_template(
            PromptTemplate.GENERAL_ASSISTANCE,
            sample_task,
            sample_context
        )
        
        assert "TESTING MODE ACTIVE" in result

    @pytest.mark.asyncio
    async def test_build_prompt_success(self, mock_git_service, sample_task, sample_context):
        """Test successful prompt building"""
        builder = PromptBuilder(git_service=mock_git_service)
        
        result = await builder.build_prompt(sample_task, sample_context)
        
        assert isinstance(result, BuiltPrompt)
        assert result.template_used == PromptTemplate.CODE_ANALYSIS
        assert result.estimated_tokens > 0
        assert len(result.context_files) == 2
        assert result.metadata["task_type"] == TaskType.CODE_ANALYSIS

    @pytest.mark.asyncio
    async def test_build_prompt_with_optimization(self, mock_git_service, sample_task, sample_context):
        """Test prompt building with optimization for large content"""
        builder = PromptBuilder(git_service=mock_git_service)
        builder.max_prompt_tokens = 100  # Very small limit to trigger optimization
        
        # Mock large file content
        mock_git_service.get_file_content.return_value = "x" * 10000
        
        result = await builder.build_prompt(sample_task, sample_context)
        
        assert result.truncated is True
        assert len(result.warnings) > 0
        assert "truncated" in result.warnings[0].lower()

    @pytest.mark.asyncio
    async def test_build_prompt_different_task_types(self, mock_git_service, sample_context):
        """Test prompt building for different task types"""
        builder = PromptBuilder(git_service=mock_git_service)
        
        task_types = [
            (TaskType.FEATURE_IMPLEMENTATION, PromptTemplate.FEATURE_IMPLEMENTATION),
            (TaskType.BUG_INVESTIGATION, PromptTemplate.BUG_INVESTIGATION),
            (TaskType.REFACTORING, PromptTemplate.REFACTORING),
            (TaskType.DOCUMENTATION, PromptTemplate.DOCUMENTATION),
            (TaskType.CODE_REVIEW, PromptTemplate.CODE_ANALYSIS),
            (TaskType.RESEARCH, PromptTemplate.GENERAL_ASSISTANCE),
            (TaskType.QUESTION, PromptTemplate.GENERAL_ASSISTANCE)
        ]
        
        for task_type, expected_template in task_types:
            task = ParsedTask(
                task_type=task_type,
                priority=TaskPriority.MEDIUM,
                prompt=f"Test {task_type.value} task",
                relevant_files=[],
                context="",
                output_format=OutputFormat.ANALYSIS_REPORT,
                estimated_complexity="Medium",
                validation_errors=[],
                raw_issue_body=f"### Task Type\n{task_type.value}\n### Detailed Prompt\nTest task"
            )
            
            result = await builder.build_prompt(task, sample_context)
            assert result.template_used == expected_template

    def test_optimize_prompt_no_truncation_needed(self, mock_git_service):
        """Test prompt optimization when no truncation is needed"""
        builder = PromptBuilder(git_service=mock_git_service)
        
        short_prompt = "Short prompt"
        context = PromptContext(
            repository_name="test/repo",
            issue_number=1,
            job_id="test",
            working_directory="/tmp"
        )
        
        result = builder._optimize_prompt(short_prompt, context)
        
        assert result.truncated is False
        assert len(result.warnings) == 0
        assert result.prompt == short_prompt

    def test_optimize_prompt_with_truncation(self, mock_git_service):
        """Test prompt optimization with truncation"""
        builder = PromptBuilder(git_service=mock_git_service)
        builder.max_prompt_tokens = 10  # Very small limit
        
        long_prompt = "x" * 1000
        context = PromptContext(
            repository_name="test/repo",
            issue_number=1,
            job_id="test",
            working_directory="/tmp",
            file_contents={"large_file.py": "x" * 500}
        )
        
        result = builder._optimize_prompt(long_prompt, context)
        
        assert result.truncated is True
        assert len(result.warnings) > 0


if __name__ == "__main__":
    pytest.main([__file__])