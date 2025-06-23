"""
Tests for Result Processor
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from src.services.result_processor import (
    ResultProcessor, ParsedResult, GitHubOutput, CodeChange,
    ResultType, OutputFormat, ResultProcessorError
)
from src.services.claude_code_service import ClaudeExecutionResult, ClaudeProcessStatus
from src.services.github_client import GitHubClient
from src.services.git_service import GitService

# Enable async test support
pytest_plugins = ('pytest_asyncio',)


class TestResultProcessor:
    """Test cases for ResultProcessor"""

    @pytest.fixture
    def mock_github_client(self):
        """Mock GitHub client"""
        client = MagicMock(spec=GitHubClient)
        client.create_comment = AsyncMock(return_value={"id": 123})
        client.add_labels = AsyncMock()
        return client

    @pytest.fixture
    def mock_git_service(self):
        """Mock git service"""
        return MagicMock(spec=GitService)

    @pytest.fixture
    def sample_code_execution_result(self):
        """Sample execution result with code changes"""
        return ClaudeExecutionResult(
            status=ClaudeProcessStatus.COMPLETED,
            stdout="""# Code Analysis Results

I've analyzed the code and found several improvements:

## Recommended Changes

### main.py

```python
def improved_function():
    # Better implementation
    return "optimized result"
```

This change improves performance by 50%.

### utils.py

```python
def helper_function():
    # New helper function
    pass
```

## Recommendations

1. Add type hints to all functions
2. Implement proper error handling
3. Add unit tests for critical functions

The files `main.py` and `utils.py` should be updated according to these suggestions.""",
            execution_time=45.0,
            command=["claude", "analyze"]
        )

    @pytest.fixture
    def sample_analysis_execution_result(self):
        """Sample execution result with analysis"""
        return ClaudeExecutionResult(
            status=ClaudeProcessStatus.COMPLETED,
            stdout="""# Performance Analysis Report

## Summary
The application shows good overall performance with some areas for improvement.

## Key Findings

1. Database queries could be optimized
2. Memory usage is within acceptable limits
3. Response times are generally good

## Recommendations

- Consider adding database indexes
- Implement caching for frequently accessed data
- Monitor memory usage during peak loads

The analysis covered `main.py`, `database.py`, and `cache.py` files.""",
            execution_time=30.0,
            command=["claude", "analyze", "performance"]
        )

    def test_initialization(self, mock_github_client, mock_git_service):
        """Test result processor initialization"""
        processor = ResultProcessor(
            github_client=mock_github_client,
            git_service=mock_git_service
        )
        
        assert processor.github_client == mock_github_client
        assert processor.git_service == mock_git_service

    def test_determine_result_type_code_changes(self):
        """Test result type determination for code changes"""
        processor = ResultProcessor()
        
        output_with_code = "Here's the fix:\n```python\nprint('hello')\n```"
        result_type = processor._determine_result_type(output_with_code, [])
        
        assert result_type == ResultType.CODE_CHANGES

    def test_determine_result_type_analysis(self):
        """Test result type determination for analysis"""
        processor = ResultProcessor()
        
        output_with_analysis = "Performance analysis shows good results"
        result_type = processor._determine_result_type(output_with_analysis, [])
        
        assert result_type == ResultType.ANALYSIS_REPORT

    def test_extract_code_changes(self):
        """Test code change extraction"""
        processor = ResultProcessor()
        
        output = """Here are the changes:

### main.py
```python
def new_function():
    return "improved"
```

### utils.py
```javascript
function helper() {
    return true;
}
```"""
        
        changes = processor._extract_code_changes(output)
        
        assert len(changes) == 2
        assert changes[0].file_path == "main.py"
        assert "def new_function():" in changes[0].new_content
        assert changes[1].file_path == "utils.py"
        assert "function helper()" in changes[1].new_content

    def test_extract_recommendations(self):
        """Test recommendation extraction"""
        processor = ResultProcessor()
        
        output = """Analysis complete. Here are my recommendations:

1. Add type hints to functions
2. Implement error handling
3. Write unit tests

I also suggest considering performance optimizations."""
        
        recommendations = processor._extract_recommendations(output)
        
        assert len(recommendations) >= 3
        assert "Add type hints to functions" in recommendations
        assert "Implement error handling" in recommendations

    def test_extract_file_references(self):
        """Test file reference extraction"""
        processor = ResultProcessor()
        
        output = "Please check `main.py` and `utils.js` for the issues in `config.yml`"
        
        file_refs = processor._extract_file_references(output)
        
        assert "main.py" in file_refs
        assert "utils.js" in file_refs
        assert "config.yml" in file_refs

    @pytest.mark.asyncio
    async def test_process_result_success(self, sample_code_execution_result):
        """Test successful result processing"""
        processor = ResultProcessor()
        
        result = await processor.process_result(
            sample_code_execution_result,
            job_id="test-job",
            repository="test/repo",
            issue_number=123
        )
        
        assert isinstance(result, ParsedResult)
        assert result.result_type == ResultType.CODE_CHANGES
        assert len(result.code_changes) == 2
        assert len(result.recommendations) >= 3
        assert result.confidence_score > 0.5
        assert result.metadata["job_id"] == "test-job"

    @pytest.mark.asyncio
    async def test_process_result_failed_execution(self):
        """Test processing of failed execution"""
        processor = ResultProcessor()
        
        failed_result = ClaudeExecutionResult(
            status=ClaudeProcessStatus.FAILED,
            stderr="Command failed",
            return_code=1
        )
        
        with pytest.raises(ResultProcessorError, match="Cannot process failed execution"):
            await processor.process_result(
                failed_result,
                job_id="test-job",
                repository="test/repo",
                issue_number=123
            )

    def test_calculate_confidence_score(self, sample_code_execution_result):
        """Test confidence score calculation"""
        processor = ResultProcessor()
        
        parsed_result = ParsedResult(
            result_type=ResultType.CODE_CHANGES,
            summary="Test summary",
            code_changes=[CodeChange("test.py", new_content="test")],
            recommendations=["Test recommendation"],
            file_references=["test.py"]
        )
        
        score = processor._calculate_confidence_score(
            sample_code_execution_result,
            parsed_result
        )
        
        assert 0.0 <= score <= 1.0
        assert score > 0.5  # Should be relatively high with good content

    @pytest.mark.asyncio
    async def test_format_as_markdown_comment(self, sample_code_execution_result):
        """Test markdown comment formatting"""
        processor = ResultProcessor()
        
        # Process result first
        parsed_result = await processor.process_result(
            sample_code_execution_result,
            job_id="test-job",
            repository="test/repo",
            issue_number=123
        )
        
        # Format as markdown
        github_output = await processor.format_for_github(
            parsed_result,
            OutputFormat.MARKDOWN_COMMENT
        )
        
        assert github_output.format_type == OutputFormat.MARKDOWN_COMMENT
        assert "Code Changes" in github_output.primary_comment
        assert "```python" in github_output.primary_comment
        assert "Recommendations" in github_output.primary_comment
        assert len(github_output.suggested_labels) > 0

    @pytest.mark.asyncio
    async def test_format_as_threaded_comments(self, sample_code_execution_result):
        """Test threaded comment formatting"""
        processor = ResultProcessor()
        
        # Process result first
        parsed_result = await processor.process_result(
            sample_code_execution_result,
            job_id="test-job",
            repository="test/repo",
            issue_number=123
        )
        
        # Format as threaded comments
        github_output = await processor.format_for_github(
            parsed_result,
            OutputFormat.THREADED_COMMENTS
        )
        
        assert github_output.format_type == OutputFormat.THREADED_COMMENTS
        assert len(github_output.additional_comments) == 2  # Two code changes
        assert "main.py" in github_output.additional_comments[0]["content"]

    @pytest.mark.asyncio
    async def test_format_as_pull_request(self, sample_code_execution_result):
        """Test pull request formatting"""
        processor = ResultProcessor()
        
        # Process result first
        parsed_result = await processor.process_result(
            sample_code_execution_result,
            job_id="test-job",
            repository="test/repo",
            issue_number=123
        )
        
        # Format as PR
        github_output = await processor.format_for_github(
            parsed_result,
            OutputFormat.PULL_REQUEST
        )
        
        assert github_output.format_type == OutputFormat.PULL_REQUEST
        assert github_output.pr_title is not None
        assert github_output.pr_description is not None
        assert len(github_output.file_changes) == 2
        assert "main.py" in github_output.file_changes

    @pytest.mark.asyncio
    async def test_format_as_issue_update(self, sample_analysis_execution_result):
        """Test issue update formatting"""
        processor = ResultProcessor()
        
        # Process result first
        parsed_result = await processor.process_result(
            sample_analysis_execution_result,
            job_id="test-job",
            repository="test/repo",
            issue_number=123
        )
        
        # Format as issue update
        github_output = await processor.format_for_github(
            parsed_result,
            OutputFormat.ISSUE_UPDATE
        )
        
        assert github_output.format_type == OutputFormat.ISSUE_UPDATE
        assert "Status Update" in github_output.primary_comment
        assert "agent:completed" in github_output.suggested_labels

    @pytest.mark.asyncio
    async def test_post_to_github_success(self, mock_github_client):
        """Test successful GitHub posting"""
        processor = ResultProcessor(github_client=mock_github_client)
        
        github_output = GitHubOutput(
            format_type=OutputFormat.MARKDOWN_COMMENT,
            primary_comment="Test comment",
            suggested_labels=["test", "automated"]
        )
        
        results = await processor.post_to_github(
            github_output,
            repository="test/repo",
            issue_number=123
        )
        
        assert results["primary_comment"]["id"] == 123
        mock_github_client.create_comment.assert_called_once()
        mock_github_client.add_labels.assert_called_once()

    @pytest.mark.asyncio
    async def test_post_to_github_no_client(self):
        """Test GitHub posting without client"""
        processor = ResultProcessor()  # No GitHub client
        
        github_output = GitHubOutput(
            format_type=OutputFormat.MARKDOWN_COMMENT,
            primary_comment="Test comment"
        )
        
        with pytest.raises(ResultProcessorError, match="GitHub client not configured"):
            await processor.post_to_github(
                github_output,
                repository="test/repo",
                issue_number=123
            )

    def test_get_language_from_extension(self):
        """Test language detection from file extension"""
        processor = ResultProcessor()
        
        assert processor._get_language_from_extension("test.py") == "python"
        assert processor._get_language_from_extension("test.js") == "javascript"
        assert processor._get_language_from_extension("test.md") == "markdown"
        assert processor._get_language_from_extension("test.unknown") == "text"

    def test_suggest_labels(self):
        """Test label suggestion logic"""
        processor = ResultProcessor()
        
        # High confidence code changes
        result = ParsedResult(
            result_type=ResultType.CODE_CHANGES,
            summary="Test",
            confidence_score=0.9
        )
        
        labels = processor._suggest_labels(result)
        
        assert "enhancement" in labels
        assert "code-change" in labels
        assert "high-confidence" in labels

    def test_guess_file_path(self):
        """Test file path guessing from context"""
        processor = ResultProcessor()
        
        full_text = """Looking at main.py, here's the fix:
        
```python
def fixed_function():
    pass
```

This should resolve the issue in main.py."""
        
        code_content = "def fixed_function():\n    pass"
        file_path = processor._guess_file_path(full_text, code_content, "python")
        
        assert file_path == "main.py"

    def test_extract_change_description(self):
        """Test change description extraction"""
        processor = ResultProcessor()
        
        full_text = """Here's an improvement for performance:

```python
def optimized_function():
    pass
```"""
        
        code_content = "def optimized_function():\n    pass"
        description = processor._extract_change_description(full_text, code_content)
        
        assert "improvement for performance" in description


if __name__ == "__main__":
    pytest.main([__file__])