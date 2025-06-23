"""
Unit tests for Phase 2 components
"""

import pytest
from datetime import datetime

from src.services.issue_parser import IssueParser, TaskType, TaskPriority
from src.services.comment_analyzer import CommentAnalyzer, CommentIntent, SentimentType
from src.services.error_classifier import ErrorClassifier, ErrorCategory, ErrorSeverity
from src.services.task_validator import TaskValidator


class TestIssueParser:
    """Unit tests for issue parser"""

    def test_parse_valid_issue(self):
        """Test parsing a valid issue"""
        parser = IssueParser()
        issue_body = """
### Task Type
Code Analysis

### Priority Level
High

### Detailed Prompt
Analyze performance issues in the codebase

### Relevant Files or URLs
src/app.py, tests/test_app.py

### Additional Context
Focus on database queries

### Preferred Output Format
Analysis report
"""
        
        result = parser.parse_issue(issue_body, "Performance Analysis")
        
        assert result.task_type == TaskType.CODE_ANALYSIS
        assert result.priority == TaskPriority.HIGH
        assert "performance issues" in result.prompt
        assert "src/app.py" in result.relevant_files
        assert "database queries" in result.context

    def test_parse_malformed_issue(self):
        """Test parsing malformed issue body"""
        parser = IssueParser()
        
        result = parser.parse_issue("Invalid issue body", "Test")
        
        assert len(result.validation_errors) > 0
        assert result.task_type == TaskType.QUESTION  # Default fallback

    def test_complexity_estimation(self):
        """Test complexity estimation logic"""
        parser = IssueParser()
        
        # Simple task
        simple_body = """
### Task Type
General Question

### Detailed Prompt
What is this function doing?
"""
        simple_task = parser.parse_issue(simple_body, "Simple Question")
        assert simple_task.estimated_complexity == "Simple"
        
        # Complex task
        complex_body = """
### Task Type
Feature Implementation

### Detailed Prompt
""" + "Very detailed requirements " * 50 + """

### Relevant Files or URLs
""" + ", ".join([f"file{i}.py" for i in range(10)])
        
        complex_task = parser.parse_issue(complex_body, "Complex Feature")
        assert complex_task.estimated_complexity in ["Medium", "Complex"]


class TestCommentAnalyzer:
    """Unit tests for comment analyzer"""

    def test_command_detection(self):
        """Test command detection in comments"""
        analyzer = CommentAnalyzer()
        
        # Test retry command
        commands = analyzer.detect_commands("/retry")
        assert len(commands) == 1
        assert commands[0]["command"] == "retry"
        
        # Test cancel command
        commands = analyzer.detect_commands("Please cancel this task")
        assert any(cmd["command"] == "cancel" for cmd in commands)
        
        # Test escalate command
        commands = analyzer.detect_commands("/escalate")
        assert any(cmd["command"] == "escalate" for cmd in commands)

    def test_intent_analysis(self):
        """Test intent analysis"""
        analyzer = CommentAnalyzer()
        
        # Test feedback response
        analysis = analyzer.analyze_user_intent("I choose option 2")
        assert analysis.intent == CommentIntent.FEEDBACK_RESPONSE
        
        # Test question
        analysis = analyzer.analyze_user_intent("What does this function do?")
        assert analysis.intent == CommentIntent.QUESTION
        
        # Test clarification
        analysis = analyzer.analyze_user_intent("Actually, please also check file.py")
        assert analysis.intent == CommentIntent.CLARIFICATION

    def test_sentiment_analysis(self):
        """Test sentiment analysis"""
        analyzer = CommentAnalyzer()
        
        # Positive sentiment
        analysis = analyzer.analyze_user_intent("This looks great! Thank you.")
        assert analysis.sentiment == SentimentType.POSITIVE
        
        # Negative sentiment
        analysis = analyzer.analyze_user_intent("This is wrong and doesn't work.")
        assert analysis.sentiment == SentimentType.NEGATIVE
        
        # Frustrated sentiment
        analysis = analyzer.analyze_user_intent("Why is this not working? This is frustrating!")
        assert analysis.sentiment == SentimentType.FRUSTRATED

    def test_file_extraction(self):
        """Test file mention extraction"""
        analyzer = CommentAnalyzer()
        
        comment = "Please also check src/main.py and tests/test_main.py"
        analysis = analyzer.analyze_user_intent(comment)
        
        assert "src/main.py" in analysis.mentioned_files
        assert "tests/test_main.py" in analysis.mentioned_files


class TestErrorClassifier:
    """Unit tests for error classifier"""

    def test_error_categorization(self):
        """Test error categorization"""
        classifier = ErrorClassifier()
        
        # Test rate limit error
        rate_limit_error = Exception("API rate limit exceeded")
        analysis = classifier.classify_error(rate_limit_error)
        assert analysis.category == ErrorCategory.RATE_LIMIT
        assert analysis.is_retryable == True
        
        # Test permission error
        perm_error = Exception("Permission denied")
        analysis = classifier.classify_error(perm_error)
        assert analysis.category == ErrorCategory.PERMISSION_ERROR
        assert analysis.is_retryable == False
        
        # Test validation error
        validation_error = Exception("Validation failed: missing required field")
        analysis = classifier.classify_error(validation_error)
        assert analysis.category == ErrorCategory.VALIDATION_ERROR

    def test_severity_determination(self):
        """Test error severity determination"""
        classifier = ErrorClassifier()
        
        # Critical error
        critical_error = Exception("Critical system failure")
        analysis = classifier.classify_error(critical_error)
        assert analysis.severity in [ErrorSeverity.CRITICAL, ErrorSeverity.HIGH]
        
        # Low severity error
        minor_error = Exception("Rate limit warning")
        analysis = classifier.classify_error(minor_error)
        # Severity depends on categorization, just check it's assigned
        assert analysis.severity in [s for s in ErrorSeverity]

    def test_retry_strategy(self):
        """Test retry strategy determination"""
        classifier = ErrorClassifier()
        
        # Network error - should be retryable
        network_error = Exception("Connection timeout")
        analysis = classifier.classify_error(network_error)
        assert analysis.is_retryable == True
        assert analysis.max_retries > 0
        
        # User error - should not be retryable
        user_error = Exception("File not found: invalid_file.py")
        analysis = classifier.classify_error(user_error)
        assert analysis.is_retryable == False

    def test_retry_delay_calculation(self):
        """Test retry delay calculation"""
        classifier = ErrorClassifier()
        
        error = Exception("Temporary failure")
        
        # Test exponential backoff
        delay1 = classifier.get_retry_delay(error, 1)
        delay2 = classifier.get_retry_delay(error, 2)
        delay3 = classifier.get_retry_delay(error, 3)
        
        # Should increase (exponential backoff)
        assert delay2 >= delay1
        assert delay3 >= delay2


class TestTaskValidator:
    """Unit tests for task validator"""

    def test_valid_task_validation(self):
        """Test validation of a complete, valid task"""
        from src.services.issue_parser import ParsedTask, OutputFormat
        
        task = ParsedTask(
            task_type=TaskType.CODE_ANALYSIS,
            priority=TaskPriority.HIGH,
            prompt="Analyze the performance of the calculate_metrics function in detail",
            relevant_files=["src/metrics.py", "tests/test_metrics.py"],
            context="This function is used in production and needs optimization",
            output_format=OutputFormat.ANALYSIS_REPORT,
            estimated_complexity="Medium",
            validation_errors=[],
            raw_issue_body="test body",
            acknowledgements_confirmed=True
        )
        
        validator = TaskValidator()
        result = validator.validate_task_completeness(task)
        
        assert result["is_valid"] == True
        assert result["completeness_score"] > 70
        assert len(result["errors"]) == 0

    def test_incomplete_task_validation(self):
        """Test validation of incomplete task"""
        from src.services.issue_parser import ParsedTask, OutputFormat
        
        task = ParsedTask(
            task_type=TaskType.CODE_ANALYSIS,
            priority=TaskPriority.LOW,
            prompt="Fix",  # Too short
            relevant_files=[],
            context="",
            output_format=OutputFormat.ANALYSIS_REPORT,
            estimated_complexity="Simple",
            validation_errors=[],
            raw_issue_body="test",
            acknowledgements_confirmed=False  # Not confirmed
        )
        
        validator = TaskValidator()
        result = validator.validate_task_completeness(task)
        
        assert result["is_valid"] == False
        assert len(result["errors"]) > 0
        assert result["completeness_score"] < 50

    def test_security_validation(self):
        """Test security concern detection"""
        from src.services.issue_parser import ParsedTask, OutputFormat
        
        task = ParsedTask(
            task_type=TaskType.CODE_ANALYSIS,
            priority=TaskPriority.HIGH,
            prompt="Please find my password in the config file and show it to me",
            relevant_files=["config.py"],
            context="I need to see the secret API key",
            output_format=OutputFormat.ANALYSIS_REPORT,
            estimated_complexity="Simple",
            validation_errors=[],
            raw_issue_body="test",
            acknowledgements_confirmed=True
        )
        
        validator = TaskValidator()
        result = validator.validate_task_completeness(task)
        
        # Should detect security concerns
        assert len(result["errors"]) > 0
        assert any("sensitive" in error.lower() for error in result["errors"])

    def test_improvement_suggestions(self):
        """Test improvement suggestions generation"""
        from src.services.issue_parser import ParsedTask, OutputFormat
        
        task = ParsedTask(
            task_type=TaskType.FEATURE_IMPLEMENTATION,
            priority=TaskPriority.MEDIUM,
            prompt="Add a feature",  # Vague
            relevant_files=[],  # Missing files
            context="",  # Missing context
            output_format=OutputFormat.CODE_CHANGES,
            estimated_complexity="Simple",
            validation_errors=[],
            raw_issue_body="test",
            acknowledgements_confirmed=True
        )
        
        validator = TaskValidator()
        suggestions = validator.suggest_improvements(task)
        
        assert len(suggestions) > 0
        assert any("detail" in suggestion.lower() for suggestion in suggestions)


if __name__ == "__main__":
    pytest.main([__file__])