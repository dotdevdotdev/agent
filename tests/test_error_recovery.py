"""
Comprehensive tests for Error Classification and Recovery Management
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta

from src.services.error_classifier import (
    ErrorClassifier, 
    ErrorCategory, 
    ErrorSeverity,
    ClassifiedError
)
from src.services.recovery_manager import (
    RecoveryManager,
    RecoveryStrategy,
    RecoveryAction,
    RecoveryResult,
    RecoveryManagerError
)


class TestErrorClassifier:
    """Test cases for Error Classifier"""

    @pytest.fixture
    def error_classifier(self):
        """Create error classifier instance for testing"""
        return ErrorClassifier()

    def test_git_error_classification(self, error_classifier):
        """Test classification of Git-related errors"""
        # Test various Git errors
        git_errors = [
            ("fatal: not a git repository", ErrorCategory.GIT_ERROR, ErrorSeverity.HIGH),
            ("error: failed to push some refs", ErrorCategory.GIT_ERROR, ErrorSeverity.MEDIUM),
            ("fatal: remote origin already exists", ErrorCategory.GIT_ERROR, ErrorSeverity.LOW),
            ("error: pathspec 'nonexistent' did not match any file(s)", ErrorCategory.GIT_ERROR, ErrorSeverity.MEDIUM),
            ("fatal: unable to access 'https://github.com/': SSL certificate problem", ErrorCategory.NETWORK_ERROR, ErrorSeverity.HIGH),
        ]

        for error_message, expected_category, expected_severity in git_errors:
            error = Exception(error_message)
            classified = error_classifier.classify_error(error)
            
            assert classified.category == expected_category
            assert classified.severity == expected_severity
            assert classified.original_error == error

    def test_claude_service_error_classification(self, error_classifier):
        """Test classification of Claude service errors"""
        claude_errors = [
            ("Claude execution timeout after 3600 seconds", ErrorCategory.CLAUDE_ERROR, ErrorSeverity.MEDIUM),
            ("Claude CLI not found at path", ErrorCategory.CLAUDE_ERROR, ErrorSeverity.HIGH),
            ("Claude returned non-zero exit code: 1", ErrorCategory.CLAUDE_ERROR, ErrorSeverity.MEDIUM),
            ("Permission denied: claude", ErrorCategory.SYSTEM_ERROR, ErrorSeverity.HIGH),
            ("rate limit exceeded", ErrorCategory.RATE_LIMIT, ErrorSeverity.MEDIUM),
        ]

        for error_message, expected_category, expected_severity in claude_errors:
            error = Exception(error_message)
            classified = error_classifier.classify_error(error)
            
            assert classified.category == expected_category
            assert classified.severity == expected_severity

    def test_github_api_error_classification(self, error_classifier):
        """Test classification of GitHub API errors"""
        github_errors = [
            ("GitHub API rate limit exceeded", ErrorCategory.RATE_LIMIT, ErrorSeverity.MEDIUM),
            ("GitHub API: 404 Not Found", ErrorCategory.GITHUB_API_ERROR, ErrorSeverity.MEDIUM),
            ("GitHub API: 403 Forbidden", ErrorCategory.GITHUB_API_ERROR, ErrorSeverity.HIGH),
            ("GitHub API: 500 Internal Server Error", ErrorCategory.GITHUB_API_ERROR, ErrorSeverity.HIGH),
            ("GitHub webhook signature validation failed", ErrorCategory.VALIDATION_ERROR, ErrorSeverity.HIGH),
        ]

        for error_message, expected_category, expected_severity in github_errors:
            error = Exception(error_message)
            classified = error_classifier.classify_error(error)
            
            assert classified.category == expected_category
            assert classified.severity == expected_severity

    def test_worktree_error_classification(self, error_classifier):
        """Test classification of worktree-related errors"""
        worktree_errors = [
            ("Worktree already exists", ErrorCategory.WORKTREE_ERROR, ErrorSeverity.MEDIUM),
            ("Failed to create worktree directory", ErrorCategory.WORKTREE_ERROR, ErrorSeverity.HIGH),
            ("Worktree cleanup failed", ErrorCategory.WORKTREE_ERROR, ErrorSeverity.LOW),
            ("No space left on device", ErrorCategory.SYSTEM_ERROR, ErrorSeverity.HIGH),
        ]

        for error_message, expected_category, expected_severity in worktree_errors:
            error = Exception(error_message)
            classified = error_classifier.classify_error(error)
            
            assert classified.category == expected_category

    def test_unknown_error_classification(self, error_classifier):
        """Test classification of unknown/generic errors"""
        unknown_errors = [
            "Something completely unexpected happened",
            "Random error message with no keywords",
            "Custom application error",
        ]

        for error_message in unknown_errors:
            error = Exception(error_message)
            classified = error_classifier.classify_error(error)
            
            assert classified.category == ErrorCategory.UNKNOWN
            assert classified.severity == ErrorSeverity.MEDIUM
            assert classified.message == error_message

    def test_error_pattern_matching(self, error_classifier):
        """Test that error patterns are matched correctly"""
        # Test case sensitivity
        error = Exception("FATAL: not a git repository")
        classified = error_classifier.classify_error(error)
        assert classified.category == ErrorCategory.GIT_ERROR

        # Test partial matching
        error = Exception("Some prefix: fatal: not a git repository and some suffix")
        classified = error_classifier.classify_error(error)
        assert classified.category == ErrorCategory.GIT_ERROR

    def test_severity_assessment(self, error_classifier):
        """Test severity assessment logic"""
        # High severity errors (should stop processing immediately)
        high_severity_errors = [
            "fatal: not a git repository",
            "Claude CLI not found",
            "Permission denied",
            "No space left on device",
        ]

        for error_message in high_severity_errors:
            error = Exception(error_message)
            classified = error_classifier.classify_error(error)
            assert classified.severity == ErrorSeverity.HIGH

        # Low severity errors (warnings, can continue)
        low_severity_errors = [
            "Worktree cleanup failed",
            "Warning: file not found",
        ]

        for error_message in low_severity_errors:
            error = Exception(error_message)
            classified = error_classifier.classify_error(error)
            assert classified.severity in [ErrorSeverity.LOW, ErrorSeverity.MEDIUM]

    def test_recovery_suggestions(self, error_classifier):
        """Test that appropriate recovery suggestions are provided"""
        # Test Git errors
        git_error = Exception("fatal: not a git repository")
        classified = error_classifier.classify_error(error)
        assert any("git" in suggestion.lower() for suggestion in classified.recovery_suggestions)

        # Test rate limit errors
        rate_limit_error = Exception("rate limit exceeded")
        classified = error_classifier.classify_error(rate_limit_error)
        assert any("retry" in suggestion.lower() or "wait" in suggestion.lower() 
                  for suggestion in classified.recovery_suggestions)


class TestRecoveryManager:
    """Test cases for Recovery Manager"""

    @pytest.fixture
    def mock_github_client(self):
        """Mock GitHub client for testing"""
        client = Mock()
        client.create_comment = AsyncMock()
        client.transition_agent_state = AsyncMock()
        client.get_issue_details = AsyncMock()
        return client

    @pytest.fixture
    def mock_job_manager(self):
        """Mock job manager for testing"""
        manager = Mock()
        manager.update_job_status = AsyncMock()
        manager.get_job = AsyncMock()
        return manager

    @pytest.fixture
    def mock_worktree_manager(self):
        """Mock worktree manager for testing"""
        manager = Mock()
        manager.cleanup_session = AsyncMock()
        manager.create_session = AsyncMock()
        manager.get_session_info = AsyncMock()
        return manager

    @pytest.fixture
    def recovery_manager(self, mock_github_client, mock_job_manager, mock_worktree_manager):
        """Create recovery manager instance for testing"""
        return RecoveryManager(
            github_client=mock_github_client,
            job_manager=mock_job_manager,
            worktree_manager=mock_worktree_manager
        )

    @pytest.fixture
    def sample_error_context(self):
        """Sample error context for testing"""
        return {
            "job_id": "test-job-123",
            "repository": "test/repo",
            "issue_number": 42,
            "error": Exception("Test error"),
            "attempt_count": 1,
            "previous_strategy": None
        }

    @pytest.mark.asyncio
    async def test_retry_strategy_for_transient_errors(self, recovery_manager, sample_error_context):
        """Test retry strategy for transient errors"""
        # Create a transient error (rate limit)
        error = Exception("GitHub API rate limit exceeded")
        error_classifier = ErrorClassifier()
        classified_error = error_classifier.classify_error(error)
        
        sample_error_context["error"] = error
        sample_error_context["classified_error"] = classified_error

        # Attempt recovery
        result = await recovery_manager.attempt_recovery(sample_error_context)

        assert result.strategy == RecoveryStrategy.RETRY
        assert result.success == True  # Should succeed for transient errors
        assert "retry" in result.message.lower() or "wait" in result.message.lower()

    @pytest.mark.asyncio
    async def test_worktree_recreation_strategy(self, recovery_manager, sample_error_context, mock_worktree_manager):
        """Test worktree recreation strategy for worktree errors"""
        # Create a worktree error
        error = Exception("Worktree already exists")
        error_classifier = ErrorClassifier()
        classified_error = error_classifier.classify_error(error)
        
        sample_error_context["error"] = error
        sample_error_context["classified_error"] = classified_error

        # Mock successful worktree operations
        mock_worktree_manager.cleanup_session.return_value = True
        mock_worktree_manager.create_session.return_value = Mock()

        # Attempt recovery
        result = await recovery_manager.attempt_recovery(sample_error_context)

        assert result.strategy == RecoveryStrategy.RECREATE_WORKTREE
        assert mock_worktree_manager.cleanup_session.called
        assert mock_worktree_manager.create_session.called

    @pytest.mark.asyncio
    async def test_escalation_for_critical_errors(self, recovery_manager, sample_error_context):
        """Test escalation for critical errors that cannot be recovered"""
        # Create a critical error
        error = Exception("Claude CLI not found at path")
        error_classifier = ErrorClassifier()
        classified_error = error_classifier.classify_error(error)
        
        sample_error_context["error"] = error
        sample_error_context["classified_error"] = classified_error

        # Attempt recovery
        result = await recovery_manager.attempt_recovery(sample_error_context)

        assert result.strategy == RecoveryStrategy.ESCALATE
        assert result.success == False
        assert "escalat" in result.message.lower() or "human" in result.message.lower()

    @pytest.mark.asyncio
    async def test_max_retry_attempts_exceeded(self, recovery_manager, sample_error_context):
        """Test escalation when max retry attempts are exceeded"""
        # Create a transient error but with high attempt count
        error = Exception("Temporary network error")
        error_classifier = ErrorClassifier()
        classified_error = error_classifier.classify_error(error)
        
        sample_error_context["error"] = error
        sample_error_context["classified_error"] = classified_error
        sample_error_context["attempt_count"] = recovery_manager.max_retry_attempts + 1

        # Attempt recovery
        result = await recovery_manager.attempt_recovery(sample_error_context)

        assert result.strategy == RecoveryStrategy.ESCALATE
        assert result.success == False
        assert "maximum" in result.message.lower() or "escalat" in result.message.lower()

    @pytest.mark.asyncio
    async def test_strategy_selection_logic(self, recovery_manager):
        """Test that correct recovery strategies are selected for different error types"""
        error_classifier = ErrorClassifier()

        # Test strategy selection for different error categories
        test_cases = [
            (ErrorCategory.RATE_LIMIT, RecoveryStrategy.RETRY),
            (ErrorCategory.NETWORK_ERROR, RecoveryStrategy.RETRY),
            (ErrorCategory.WORKTREE_ERROR, RecoveryStrategy.RECREATE_WORKTREE),
            (ErrorCategory.GIT_ERROR, RecoveryStrategy.RECREATE_WORKTREE),
            (ErrorCategory.CLAUDE_ERROR, RecoveryStrategy.RESTART_PROCESS),
        ]

        for category, expected_strategy in test_cases:
            # Create a mock classified error
            classified_error = ClassifiedError(
                category=category,
                severity=ErrorSeverity.MEDIUM,
                message="Test error",
                original_error=Exception("Test"),
                recovery_suggestions=[]
            )

            strategy = recovery_manager._select_recovery_strategy(classified_error, attempt_count=1)
            assert strategy == expected_strategy

    @pytest.mark.asyncio
    async def test_recovery_backoff_timing(self, recovery_manager):
        """Test exponential backoff for retry attempts"""
        base_delay = recovery_manager.base_retry_delay
        
        # Test backoff calculation
        for attempt in range(1, 5):
            delay = recovery_manager._calculate_retry_delay(attempt)
            expected_delay = base_delay * (2 ** (attempt - 1))
            assert delay == expected_delay

    @pytest.mark.asyncio
    async def test_recovery_context_preservation(self, recovery_manager, sample_error_context):
        """Test that recovery context is properly preserved across attempts"""
        # Simulate multiple recovery attempts
        context = sample_error_context.copy()
        
        for attempt in range(1, 4):
            context["attempt_count"] = attempt
            result = await recovery_manager.attempt_recovery(context)
            
            # Verify context is updated
            assert result.attempt_count == attempt
            assert result.context_preserved == True

    @pytest.mark.asyncio
    async def test_recovery_notification_to_github(self, recovery_manager, sample_error_context, mock_github_client):
        """Test that recovery attempts are properly communicated to GitHub"""
        # Attempt recovery
        result = await recovery_manager.attempt_recovery(sample_error_context)

        # Verify GitHub client was called to update the issue
        assert mock_github_client.create_comment.called or mock_github_client.transition_agent_state.called

    @pytest.mark.asyncio
    async def test_concurrent_recovery_attempts(self, recovery_manager):
        """Test handling of concurrent recovery attempts for different jobs"""
        # Create multiple error contexts
        contexts = []
        for i in range(3):
            context = {
                "job_id": f"test-job-{i}",
                "repository": "test/repo",
                "issue_number": i + 1,
                "error": Exception(f"Test error {i}"),
                "attempt_count": 1
            }
            contexts.append(context)

        # Attempt recovery concurrently
        tasks = [recovery_manager.attempt_recovery(ctx) for ctx in contexts]
        results = await asyncio.gather(*tasks)

        # Verify all recoveries were attempted
        assert len(results) == 3
        for result in results:
            assert isinstance(result, RecoveryResult)

    @pytest.mark.asyncio
    async def test_recovery_manager_error_handling(self, recovery_manager, sample_error_context, mock_github_client):
        """Test error handling within the recovery manager itself"""
        # Mock GitHub client to raise an exception
        mock_github_client.create_comment.side_effect = Exception("GitHub API error during recovery")

        # Attempt recovery (should handle internal errors gracefully)
        result = await recovery_manager.attempt_recovery(sample_error_context)

        # Recovery manager should not crash, should escalate instead
        assert isinstance(result, RecoveryResult)
        assert result.strategy == RecoveryStrategy.ESCALATE

    @pytest.mark.asyncio
    async def test_recovery_history_tracking(self, recovery_manager, sample_error_context):
        """Test that recovery history is properly tracked"""
        # Simulate multiple recovery attempts for the same job
        job_id = sample_error_context["job_id"]
        
        for attempt in range(1, 4):
            context = sample_error_context.copy()
            context["attempt_count"] = attempt
            
            result = await recovery_manager.attempt_recovery(context)
            
            # Check that history is maintained
            history = recovery_manager.get_recovery_history(job_id)
            assert len(history) == attempt
            assert history[-1]["attempt"] == attempt

    def test_recovery_strategy_enum_coverage(self):
        """Test that all recovery strategies are properly defined and accessible"""
        # Verify all expected strategies exist
        expected_strategies = [
            RecoveryStrategy.RETRY,
            RecoveryStrategy.RECREATE_WORKTREE,
            RecoveryStrategy.RESTART_PROCESS,
            RecoveryStrategy.ESCALATE,
            RecoveryStrategy.ROLLBACK
        ]

        for strategy in expected_strategies:
            assert isinstance(strategy, RecoveryStrategy)
            assert hasattr(strategy, 'value')

    def test_error_category_enum_coverage(self):
        """Test that all error categories are properly defined"""
        expected_categories = [
            ErrorCategory.GIT_ERROR,
            ErrorCategory.GITHUB_API_ERROR,
            ErrorCategory.CLAUDE_ERROR,
            ErrorCategory.WORKTREE_ERROR,
            ErrorCategory.NETWORK_ERROR,
            ErrorCategory.RATE_LIMIT,
            ErrorCategory.VALIDATION_ERROR,
            ErrorCategory.SYSTEM_ERROR,
            ErrorCategory.UNKNOWN
        ]

        for category in expected_categories:
            assert isinstance(category, ErrorCategory)
            assert hasattr(category, 'value')

    def test_error_severity_ordering(self):
        """Test that error severity levels are properly ordered"""
        severities = [ErrorSeverity.LOW, ErrorSeverity.MEDIUM, ErrorSeverity.HIGH]
        
        # Test that severities can be compared
        assert ErrorSeverity.LOW < ErrorSeverity.MEDIUM < ErrorSeverity.HIGH
        
        # Test that they have appropriate values
        for severity in severities:
            assert isinstance(severity, ErrorSeverity)
            assert hasattr(severity, 'value')