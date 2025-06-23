"""
Comprehensive integration tests for Phase 2 components
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta

from src.services.issue_parser import IssueParser, ParsedTask, TaskType, TaskPriority
from src.services.task_validator import TaskValidator
from src.services.agent_state_machine import AgentStateMachine, AgentState
from src.services.progress_reporter import ProgressReporter
from src.services.event_router import EventRouter
from src.services.comment_analyzer import CommentAnalyzer, CommentIntent
from src.services.conversation_manager import ConversationManager
from src.services.response_generator import ResponseGenerator
from src.services.error_classifier import ErrorClassifier, ErrorCategory
from src.services.recovery_manager import RecoveryManager
from src.services.health_monitor import HealthMonitor


class TestPhase2Integration:
    """Integration tests for enhanced GitHub integration"""

    @pytest.fixture
    def mock_github_client(self):
        """Mock GitHub client for testing"""
        client = Mock()
        client.create_comment = AsyncMock()
        client.add_label = AsyncMock()
        client.remove_label = AsyncMock()
        client.transition_agent_state = AsyncMock()
        client.create_validation_feedback = AsyncMock()
        client.get_current_agent_state = AsyncMock(return_value="agent:queued")
        return client

    @pytest.fixture
    def mock_job_manager(self):
        """Mock job manager for testing"""
        manager = Mock()
        manager.create_job = AsyncMock()
        manager.update_job_status = AsyncMock()
        manager.get_job = AsyncMock()
        manager.list_jobs = AsyncMock(return_value=[])
        return manager

    @pytest.fixture
    def sample_issue_body(self):
        """Sample GitHub issue body with template format"""
        return """
### Task Type
Code Analysis

### Priority Level
High

### Detailed Prompt
Please analyze the performance of the calculate_metrics function and suggest optimizations for better efficiency.

### Relevant Files or URLs
src/metrics.py, tests/test_metrics.py

### Additional Context
The function is currently taking too long to process large datasets and needs optimization.

### Preferred Output Format
Analysis report

### Acknowledgements
- [x] I understand this task will be processed by an AI agent.
- [x] I have provided sufficient detail for the agent to complete this task.
"""

    @pytest.mark.asyncio
    async def test_complete_issue_workflow(self, mock_github_client, mock_job_manager, sample_issue_body):
        """Test complete workflow from issue creation to completion"""
        
        # Initialize components
        state_machine = AgentStateMachine(mock_github_client, mock_job_manager)
        event_router = EventRouter(mock_github_client, mock_job_manager, state_machine)
        
        # Create test payload
        payload = {
            "action": "opened",
            "issue": {
                "number": 123,
                "title": "Test Issue",
                "body": sample_issue_body,
                "labels": [{"name": "agent:queued"}]
            },
            "repository": {
                "full_name": "test/repo"
            }
        }

        # Process the event
        result = await event_router.route_event("issues", payload)
        
        # Verify the workflow
        assert result["status"] == "accepted"
        assert "job_id" in result
        
        # Verify GitHub interactions
        mock_github_client.transition_agent_state.assert_called()
        mock_job_manager.create_job.assert_called()

    @pytest.mark.asyncio
    async def test_issue_parsing_and_validation(self, sample_issue_body):
        """Test issue parsing and validation flow"""
        
        # Test parsing
        parser = IssueParser()
        parsed_task = parser.parse_issue(sample_issue_body, "Test Issue")
        
        assert parsed_task.task_type == TaskType.CODE_ANALYSIS
        assert parsed_task.priority == TaskPriority.HIGH
        assert "calculate_metrics" in parsed_task.prompt
        assert "src/metrics.py" in parsed_task.relevant_files
        assert parsed_task.acknowledgements_confirmed == True

        # Test validation
        validator = TaskValidator()
        validation_result = validator.validate_task_completeness(parsed_task)
        
        assert validation_result["is_valid"] == True
        assert validation_result["completeness_score"] > 70
        assert len(validation_result["errors"]) == 0

    @pytest.mark.asyncio
    async def test_state_machine_transitions(self, mock_github_client, mock_job_manager):
        """Test all state machine transitions"""
        
        state_machine = AgentStateMachine(mock_github_client, mock_job_manager)
        
        # Initialize context
        context = await state_machine.initialize_context("test-job", "test/repo", 123)
        
        # Test valid transitions
        transitions = [
            (AgentState.QUEUED, AgentState.VALIDATING),
            (AgentState.VALIDATING, AgentState.ANALYZING),
            (AgentState.ANALYZING, AgentState.IN_PROGRESS),
            (AgentState.IN_PROGRESS, AgentState.IMPLEMENTING),
            (AgentState.IMPLEMENTING, AgentState.TESTING),
            (AgentState.TESTING, AgentState.COMPLETED)
        ]
        
        for from_state, to_state in transitions:
            # Update current state
            context.current_state = from_state
            
            # Test transition
            success = await state_machine.transition_to("test-job", to_state)
            assert success == True
            
            # Verify state updated
            assert context.current_state == to_state

    @pytest.mark.asyncio
    async def test_conversation_flow(self):
        """Test multi-turn conversation handling"""
        
        conversation_manager = ConversationManager()
        
        # Start conversation
        parsed_task = ParsedTask(
            task_type=TaskType.CODE_ANALYSIS,
            priority=TaskPriority.MEDIUM,
            prompt="Test task",
            relevant_files=[],
            context="Test context",
            output_format="Analysis report",
            estimated_complexity="Simple",
            validation_errors=[],
            raw_issue_body="test"
        )
        
        context = await conversation_manager.start_conversation("test/repo", 123, parsed_task)
        assert context.conversation_id == "test/repo:123"
        assert len(context.turns) == 1  # Initial task submission
        
        # Add user response
        await conversation_manager.add_turn(
            "test/repo:123", "user", "Thanks for the update!", "acknowledgment"
        )
        
        # Add agent response
        await conversation_manager.add_turn(
            "test/repo:123", "agent", "You're welcome! Continuing with the task.", "progress_update"
        )
        
        # Verify conversation state
        assert len(context.turns) == 3
        
        # Test context retrieval
        recent_context = await conversation_manager.get_relevant_context("test/repo:123", max_turns=2)
        assert len(recent_context) == 2

    @pytest.mark.asyncio
    async def test_comment_analysis_and_response(self):
        """Test comment analysis and response generation"""
        
        analyzer = CommentAnalyzer()
        conversation_manager = ConversationManager()
        response_generator = ResponseGenerator(conversation_manager)
        
        # Test command detection
        commands = analyzer.detect_commands("/retry")
        assert len(commands) == 1
        assert commands[0]["command"] == "retry"
        
        # Test intent analysis
        analysis = analyzer.analyze_user_intent("This looks great! Please proceed with the implementation.")
        assert analysis.intent in [CommentIntent.APPROVAL, CommentIntent.GENERAL_COMMENT]
        assert analysis.sentiment.value in ["positive", "satisfied"]
        
        # Test response generation
        context = await conversation_manager.start_conversation("test/repo", 123)
        acknowledgment = await response_generator.generate_user_response_acknowledgment(
            "test/repo:123", analysis
        )
        
        assert "thanks" in acknowledgment.lower() or "great" in acknowledgment.lower()

    @pytest.mark.asyncio
    async def test_error_handling_and_recovery(self, mock_github_client, mock_job_manager):
        """Test error handling and recovery mechanisms"""
        
        # Initialize components
        state_machine = AgentStateMachine(mock_github_client, mock_job_manager)
        recovery_manager = RecoveryManager(mock_github_client, state_machine)
        
        # Test error classification
        test_error = Exception("GitHub API rate limit exceeded")
        context = {"job_id": "test-job", "operation": "github_api"}
        
        analysis = recovery_manager.classifier.classify_error(test_error, context)
        assert analysis.category == ErrorCategory.RATE_LIMIT
        assert analysis.is_retryable == True
        
        # Test recovery handling
        await state_machine.initialize_context("test-job", "test/repo", 123)
        success = await recovery_manager.handle_error("test-job", test_error, context)
        
        # Rate limit errors should be automatically retried
        assert success == True or analysis.escalation_required == False

    @pytest.mark.asyncio
    async def test_progress_reporting(self, mock_github_client):
        """Test progress reporting with rich formatting"""
        
        reporter = ProgressReporter(mock_github_client)
        
        # Test progress comment creation
        await reporter.create_progress_comment(
            "test/repo", 123, AgentState.IN_PROGRESS, 50,
            "Making good progress on your task",
            technical_details="Processing src/metrics.py",
            steps_completed=["Analysis complete", "Planning done"],
            next_steps=["Begin implementation", "Run tests"]
        )
        
        # Verify GitHub comment was created
        mock_github_client.create_comment.assert_called()
        call_args = mock_github_client.create_comment.call_args
        
        assert call_args[0][0] == "test/repo"
        assert call_args[0][1] == 123
        comment_body = call_args[0][2]
        
        # Verify rich formatting
        assert "Progress Update" in comment_body
        assert "50%" in comment_body
        assert "Making good progress" in comment_body
        assert "✅ Completed Steps" in comment_body
        assert "🔄 Next Steps" in comment_body

    @pytest.mark.asyncio
    async def test_webhook_event_routing(self, mock_github_client, mock_job_manager):
        """Test webhook event routing for different event types"""
        
        state_machine = AgentStateMachine(mock_github_client, mock_job_manager)
        event_router = EventRouter(mock_github_client, mock_job_manager, state_machine)
        
        # Test issue events
        issue_payload = {
            "action": "opened",
            "issue": {"number": 123, "title": "Test", "body": "### Task Type\nCode Analysis"},
            "repository": {"full_name": "test/repo"}
        }
        
        result = await event_router.route_event("issues", issue_payload)
        assert result["status"] in ["accepted", "validation_failed"]
        
        # Test comment events
        comment_payload = {
            "action": "created",
            "comment": {"body": "/retry", "user": {"login": "testuser", "type": "User"}},
            "issue": {"number": 123},
            "repository": {"full_name": "test/repo"}
        }
        
        result = await event_router.route_event("issue_comment", comment_payload)
        assert result["status"] in ["processed", "ignored"]

    @pytest.mark.asyncio
    async def test_health_monitoring(self, mock_github_client, mock_job_manager):
        """Test system health monitoring"""
        
        # Mock dependencies to avoid requiring psutil
        with patch('src.services.health_monitor.psutil') as mock_psutil:
            mock_psutil.cpu_percent.return_value = 45.0
            mock_psutil.virtual_memory.return_value.percent = 60.0
            mock_psutil.disk_usage.return_value.percent = 50.0
            mock_psutil.getloadavg.return_value = [1.0, 1.2, 1.1]
            
            monitor = HealthMonitor(mock_github_client, mock_job_manager)
            
            # Test GitHub API health check
            github_health = await monitor.check_github_api_health()
            assert "status" in github_health
            
            # Test job processing health
            job_health = await monitor.check_job_processing_health()
            assert "status" in job_health
            assert "active_jobs" in job_health
            
            # Test system resources
            system_health = await monitor.check_system_resources()
            assert "status" in system_health
            assert "memory_percent" in system_health
            
            # Test comprehensive health report
            health_report = await monitor.generate_health_report()
            assert health_report.overall_status in ["healthy", "warning", "critical"]
            assert len(health_report.metrics) > 0

    @pytest.mark.asyncio
    async def test_user_feedback_loop(self, mock_github_client, mock_job_manager):
        """Test user feedback request and response handling"""
        
        state_machine = AgentStateMachine(mock_github_client, mock_job_manager)
        conversation_manager = ConversationManager()
        response_generator = ResponseGenerator(conversation_manager)
        
        # Initialize context
        await state_machine.initialize_context("test-job", "test/repo", 123)
        await conversation_manager.start_conversation("test/repo", 123)
        
        # Request feedback
        await state_machine.request_user_feedback(
            "test-job",
            "Which approach would you prefer?",
            ["Option A: Fast implementation", "Option B: Thorough analysis"],
            timeout_hours=24
        )
        
        # Verify state transition
        context = state_machine.get_context("test-job")
        assert context.current_state == AgentState.AWAITING_FEEDBACK
        
        # Simulate user response
        await state_machine.handle_user_response("test-job", "I prefer Option B", "testuser")
        
        # Verify response processing
        mock_github_client.transition_agent_state.assert_called()

    @pytest.mark.asyncio
    async def test_integration_with_existing_systems(self, mock_github_client, mock_job_manager):
        """Test integration with existing Phase 1 systems"""
        
        # Test that Phase 2 components work with existing job manager
        state_machine = AgentStateMachine(mock_github_client, mock_job_manager)
        
        # Create a job context
        context = await state_machine.initialize_context("test-job", "test/repo", 123)
        
        # Test state transitions update job status
        await state_machine.transition_to("test-job", AgentState.IN_PROGRESS)
        
        # Verify job manager was called
        mock_job_manager.update_job_status.assert_called()
        
        # Test GitHub client integration
        mock_github_client.transition_agent_state.assert_called()

    def test_data_models_compatibility(self):
        """Test that new data models are compatible with existing systems"""
        
        # Test ParsedTask serialization
        task = ParsedTask(
            task_type=TaskType.CODE_ANALYSIS,
            priority=TaskPriority.HIGH,
            prompt="Test prompt",
            relevant_files=["test.py"],
            context="Test context",
            output_format="Analysis report",
            estimated_complexity="Medium",
            validation_errors=[],
            raw_issue_body="test body"
        )
        
        # Should be serializable to dict
        task_dict = task.__dict__
        assert isinstance(task_dict, dict)
        assert "task_type" in task_dict
        
        # Test conversation context serialization
        from src.services.conversation_manager import ConversationContext
        
        conv_context = ConversationContext(
            conversation_id="test:123",
            issue_number=123,
            repository="test/repo",
            current_task=task.__dict__
        )
        
        # Should be serializable
        conv_dict = conv_context.to_dict()
        assert isinstance(conv_dict, dict)
        
        # Should be deserializable
        restored_context = ConversationContext.from_dict(conv_dict)
        assert restored_context.conversation_id == "test:123"