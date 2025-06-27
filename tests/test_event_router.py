"""
Comprehensive tests for Event Router and Event Processors
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta

from src.services.event_router import (
    EventRouter,
    IssueEventProcessor,
    CommentEventProcessor,
    LabelEventProcessor,
    PullRequestEventProcessor,
    EventProcessor
)
from src.services.github_client import GitHubClient
from src.services.job_manager import JobManager
from src.services.agent_state_machine import AgentStateMachine, AgentState


class TestEventRouter:
    """Test cases for Event Router"""

    @pytest.fixture
    def mock_github_client(self):
        """Mock GitHub client for testing"""
        client = Mock(spec=GitHubClient)
        client.create_comment = AsyncMock()
        client.add_labels = AsyncMock()
        client.remove_label = AsyncMock()
        client.transition_agent_state = AsyncMock()
        client.create_validation_feedback = AsyncMock()
        client.get_current_agent_state = AsyncMock(return_value="agent:queued")
        return client

    @pytest.fixture
    def mock_job_manager(self):
        """Mock job manager for testing"""
        manager = Mock(spec=JobManager)
        manager.create_job = AsyncMock()
        manager.update_job_status = AsyncMock()
        manager.get_job = AsyncMock()
        manager.list_jobs = AsyncMock(return_value=[])
        manager.cancel_job = AsyncMock()
        return manager

    @pytest.fixture
    def mock_state_machine(self):
        """Mock state machine for testing"""
        machine = Mock(spec=AgentStateMachine)
        machine.initialize_context = AsyncMock()
        machine.transition_to = AsyncMock()
        machine.handle_user_response = AsyncMock()
        machine.handle_error = AsyncMock()
        return machine

    @pytest.fixture
    def event_router(self, mock_github_client, mock_job_manager, mock_state_machine):
        """Create event router instance for testing"""
        return EventRouter(
            github_client=mock_github_client,
            job_manager=mock_job_manager,
            state_machine=mock_state_machine
        )

    @pytest.fixture
    def sample_issue_opened_payload(self):
        """Sample GitHub issue opened payload"""
        return {
            "action": "opened",
            "issue": {
                "number": 42,
                "title": "Test Issue",
                "body": "### Task Type\n\nCode Enhancement\n\n### What would you like me to do?\n\nImplement a new feature",
                "user": {
                    "login": "testuser"
                },
                "labels": [
                    {"name": "agent:queued"}
                ]
            },
            "repository": {
                "full_name": "test/repo",
                "id": 12345
            }
        }

    @pytest.fixture
    def sample_comment_payload(self):
        """Sample GitHub comment payload"""
        return {
            "action": "created",
            "comment": {
                "id": 123456,
                "body": "/retry",
                "user": {
                    "login": "testuser",
                    "type": "User"
                }
            },
            "issue": {
                "number": 42
            },
            "repository": {
                "full_name": "test/repo"
            }
        }

    @pytest.mark.asyncio
    async def test_route_issue_event(self, event_router, sample_issue_opened_payload):
        """Test routing of issue events"""
        result = await event_router.route_event("issues", sample_issue_opened_payload)
        
        assert result["status"] in ["accepted", "duplicate_job_prevented", "validation_failed"]
        
        # Verify a processor was called
        assert "job_id" in result or "reason" in result

    @pytest.mark.asyncio
    async def test_route_comment_event(self, event_router, sample_comment_payload, mock_github_client):
        """Test routing of comment events"""
        # Setup mock for comment processing
        mock_github_client.get_current_agent_state.return_value = "agent:in-progress"
        
        result = await event_router.route_event("issue_comment", sample_comment_payload)
        
        assert result["status"] in ["processed", "ignored"]

    @pytest.mark.asyncio
    async def test_route_unhandled_event(self, event_router):
        """Test routing of unhandled event types"""
        result = await event_router.route_event("unknown_event", {})
        
        assert result["status"] == "unhandled"
        assert "No processor for event type" in result["message"]

    @pytest.mark.asyncio
    async def test_event_deduplication(self, event_router, sample_issue_opened_payload):
        """Test that duplicate events are properly handled"""
        # Process the same event twice
        result1 = await event_router.route_event("issues", sample_issue_opened_payload)
        result2 = await event_router.route_event("issues", sample_issue_opened_payload)
        
        # Second result should indicate duplicate
        assert result2["status"] == "duplicate"

    @pytest.mark.asyncio
    async def test_event_cache_cleanup(self, event_router):
        """Test event cache cleanup functionality"""
        # Add some test events to cache
        event_router.event_cache["test1"] = datetime.now() - timedelta(minutes=35)
        event_router.event_cache["test2"] = datetime.now() - timedelta(minutes=10)
        event_router.event_cache["test3"] = datetime.now()
        
        # Run cleanup
        await event_router.cleanup_event_cache()
        
        # Old event should be removed, recent ones should remain
        assert "test1" not in event_router.event_cache
        assert "test2" in event_router.event_cache
        assert "test3" in event_router.event_cache

    def test_event_fingerprint_generation(self, event_router):
        """Test event fingerprint generation for deduplication"""
        # Test issue event fingerprint
        issue_payload = {
            "action": "opened",
            "issue": {"id": 12345},
            "repository": {"id": 67890}
        }
        
        fingerprint1 = event_router._generate_event_fingerprint("issues", issue_payload)
        fingerprint2 = event_router._generate_event_fingerprint("issues", issue_payload)
        
        # Same payload should generate same fingerprint
        assert fingerprint1 == fingerprint2
        
        # Different payloads should generate different fingerprints
        issue_payload["issue"]["id"] = 54321
        fingerprint3 = event_router._generate_event_fingerprint("issues", issue_payload)
        assert fingerprint1 != fingerprint3

    def test_event_stats(self, event_router):
        """Test event statistics reporting"""
        stats = event_router.get_event_stats()
        
        assert "cache_size" in stats
        assert "processors_count" in stats
        assert "rate_limit_window_seconds" in stats
        assert isinstance(stats["cache_size"], int)
        assert isinstance(stats["processors_count"], int)


class TestIssueEventProcessor:
    """Test cases for Issue Event Processor"""

    @pytest.fixture
    def mock_dependencies(self):
        """Mock dependencies for issue processor"""
        github_client = Mock(spec=GitHubClient)
        github_client.create_comment = AsyncMock()
        github_client.add_labels = AsyncMock()
        github_client.remove_label = AsyncMock()
        github_client.transition_agent_state = AsyncMock()
        github_client.create_validation_feedback = AsyncMock()
        github_client.get_current_agent_state = AsyncMock()
        
        job_manager = Mock(spec=JobManager)
        job_manager.create_job = AsyncMock()
        job_manager.update_job_status = AsyncMock()
        job_manager.list_jobs = AsyncMock(return_value=[])
        job_manager.cancel_job = AsyncMock()
        
        state_machine = Mock(spec=AgentStateMachine)
        state_machine.initialize_context = AsyncMock()
        state_machine.transition_to = AsyncMock()
        
        return github_client, job_manager, state_machine

    @pytest.fixture
    def issue_processor(self, mock_dependencies):
        """Create issue processor instance"""
        github_client, job_manager, state_machine = mock_dependencies
        return IssueEventProcessor(github_client, job_manager, state_machine)

    @pytest.mark.asyncio
    async def test_can_handle_issue_events(self, issue_processor):
        """Test that processor can handle issue events"""
        assert await issue_processor.can_handle("issues", {}) == True
        assert await issue_processor.can_handle("pull_request", {}) == False

    @pytest.mark.asyncio
    async def test_handle_issue_opened_valid(self, issue_processor, mock_dependencies):
        """Test handling of valid issue opened event"""
        github_client, job_manager, state_machine = mock_dependencies
        
        # Mock job creation
        mock_job = Mock()
        mock_job.job_id = "test-job-123"
        job_manager.create_job.return_value = mock_job
        
        payload = {
            "action": "opened",
            "issue": {
                "number": 42,
                "title": "Test Issue",
                "body": "### Task Type\n\nCode Enhancement\n\n### What would you like me to do?\n\nImplement a new feature\n\n### Acknowledgements\n\n- [x] I confirm this is a valid request",
                "user": {"login": "testuser"},
                "labels": [{"name": "agent:queued"}]
            },
            "repository": {
                "full_name": "test/repo"
            }
        }
        
        result = await issue_processor.process(payload)
        
        assert result["status"] == "accepted"
        assert "job_id" in result
        
        # Verify job was created
        job_manager.create_job.assert_called_once()
        state_machine.initialize_context.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_issue_opened_not_agent_task(self, issue_processor):
        """Test handling of issue that's not an agent task"""
        payload = {
            "action": "opened",
            "issue": {
                "number": 42,
                "title": "Regular Issue",
                "body": "This is just a regular issue, not an agent task",
                "labels": []
            },
            "repository": {
                "full_name": "test/repo"
            }
        }
        
        result = await issue_processor.process(payload)
        
        assert result["status"] == "ignored"
        assert result["reason"] == "Not an agent task"

    @pytest.mark.asyncio
    async def test_handle_issue_opened_duplicate_job(self, issue_processor, mock_dependencies):
        """Test handling of duplicate job creation attempt"""
        github_client, job_manager, state_machine = mock_dependencies
        
        # Mock existing job
        existing_job = Mock()
        existing_job.repository_full_name = "test/repo"
        existing_job.issue_number = 42
        existing_job.status = "pending"
        existing_job.job_id = "existing-job-123"
        
        job_manager.list_jobs.return_value = [existing_job]
        
        payload = {
            "action": "opened",
            "issue": {
                "number": 42,
                "title": "Test Issue",
                "body": "### Task Type\n\nCode Enhancement\n\n### What would you like me to do?\n\nImplement a new feature",
                "user": {"login": "testuser"},
                "labels": [{"name": "agent:queued"}]
            },
            "repository": {
                "full_name": "test/repo"
            }
        }
        
        result = await issue_processor.process(payload)
        
        assert result["status"] == "duplicate_job_prevented"
        assert result["job_id"] == "existing-job-123"

    @pytest.mark.asyncio
    async def test_handle_issue_labeled_restart(self, issue_processor, mock_dependencies):
        """Test handling of issue labeled with agent:queued for restart"""
        github_client, job_manager, state_machine = mock_dependencies
        
        # Mock failed job
        failed_job = Mock()
        failed_job.repository_full_name = "test/repo"
        failed_job.issue_number = 42
        failed_job.status = "failed"
        failed_job.job_id = "failed-job-123"
        
        job_manager.list_jobs.return_value = [failed_job]
        
        payload = {
            "action": "labeled",
            "label": {"name": "agent:queued"},
            "issue": {"number": 42},
            "repository": {"full_name": "test/repo"}
        }
        
        result = await issue_processor.process(payload)
        
        assert result["status"] == "restarted"
        assert result["job_id"] == "failed-job-123"

    @pytest.mark.asyncio
    async def test_handle_issue_closed(self, issue_processor, mock_dependencies):
        """Test handling of issue closure"""
        github_client, job_manager, state_machine = mock_dependencies
        
        # Mock active job
        active_job = Mock()
        active_job.repository_full_name = "test/repo"
        active_job.issue_number = 42
        active_job.status = "running"
        active_job.job_id = "active-job-123"
        
        job_manager.list_jobs.return_value = [active_job]
        
        payload = {
            "action": "closed",
            "issue": {"number": 42},
            "repository": {"full_name": "test/repo"}
        }
        
        result = await issue_processor.process(payload)
        
        assert result["status"] == "handled"
        
        # Verify job was cancelled
        job_manager.cancel_job.assert_called_once_with("active-job-123")
        state_machine.transition_to.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_issue_edited_awaiting_feedback(self, issue_processor, mock_dependencies):
        """Test handling of issue edited while awaiting feedback"""
        github_client, job_manager, state_machine = mock_dependencies
        
        # Mock current state
        github_client.get_current_agent_state.return_value = "agent:awaiting-feedback"
        
        payload = {
            "action": "edited",
            "issue": {"number": 42},
            "repository": {"full_name": "test/repo"},
            "changes": {"body": {"from": "old body", "to": "new body"}}
        }
        
        result = await issue_processor.process(payload)
        
        assert result["status"] == "acknowledged"
        
        # Verify comment was created
        github_client.create_comment.assert_called_once()

    @pytest.mark.asyncio
    async def test_provide_simple_response_non_admin(self, issue_processor, mock_dependencies):
        """Test simple response for non-admin users"""
        github_client, job_manager, state_machine = mock_dependencies
        
        # Create a mock parsed task
        from src.services.issue_parser import TaskType
        mock_task = Mock()
        mock_task.task_type = TaskType.QUESTION
        mock_task.prompt = "Test prompt for non-admin user"
        mock_task.issue_author = "non-admin-user"
        
        # Test the simple response method
        await issue_processor._provide_simple_response(
            "test-job-123", "test/repo", 42, mock_task
        )
        
        # Verify simple response was posted
        github_client.create_comment.assert_called_once()
        github_client.add_labels.assert_called_once_with("test/repo", 42, ["agent:completed"])
        state_machine.transition_to.assert_called()
        job_manager.update_job_status.assert_called_once()


class TestCommentEventProcessor:
    """Test cases for Comment Event Processor"""

    @pytest.fixture
    def comment_processor(self):
        """Create comment processor instance"""
        github_client = Mock(spec=GitHubClient)
        github_client.get_current_agent_state = AsyncMock()
        
        job_manager = Mock(spec=JobManager)
        job_manager.list_jobs = AsyncMock()
        
        state_machine = Mock(spec=AgentStateMachine)
        state_machine.handle_user_response = AsyncMock()
        
        return CommentEventProcessor(github_client, job_manager, state_machine)

    @pytest.mark.asyncio
    async def test_can_handle_comment_events(self, comment_processor):
        """Test that processor can handle comment events"""
        assert await comment_processor.can_handle("issue_comment", {}) == True
        assert await comment_processor.can_handle("issues", {}) == False

    @pytest.mark.asyncio
    async def test_handle_comment_created_with_active_task(self, comment_processor):
        """Test handling comment on issue with active agent task"""
        # Setup mocks
        comment_processor.github_client.get_current_agent_state.return_value = "agent:in-progress"
        
        mock_job = Mock()
        mock_job.repository_full_name = "test/repo"
        mock_job.issue_number = 42
        mock_job.status = "running"
        mock_job.job_id = "test-job-123"
        
        comment_processor.job_manager.list_jobs.return_value = [mock_job]
        
        payload = {
            "action": "created",
            "comment": {
                "body": "/retry",
                "user": {
                    "login": "testuser",
                    "type": "User"
                }
            },
            "issue": {"number": 42},
            "repository": {"full_name": "test/repo"}
        }
        
        result = await comment_processor.process(payload)
        
        assert result["status"] == "processed"
        assert result["job_id"] == "test-job-123"
        
        # Verify user response was handled
        comment_processor.state_machine.handle_user_response.assert_called_once_with(
            "test-job-123", "/retry", "testuser"
        )

    @pytest.mark.asyncio
    async def test_ignore_bot_comments(self, comment_processor):
        """Test that bot comments are ignored"""
        payload = {
            "action": "created",
            "comment": {
                "body": "Bot generated comment",
                "user": {
                    "login": "github-bot",
                    "type": "Bot"
                }
            },
            "issue": {"number": 42},
            "repository": {"full_name": "test/repo"}
        }
        
        result = await comment_processor.process(payload)
        
        assert result["status"] == "ignored"
        assert result["reason"] == "Bot comment"

    @pytest.mark.asyncio
    async def test_ignore_comment_no_active_task(self, comment_processor):
        """Test that comments are ignored when no active agent task"""
        comment_processor.github_client.get_current_agent_state.return_value = None
        
        payload = {
            "action": "created",
            "comment": {
                "body": "Some comment",
                "user": {
                    "login": "testuser",
                    "type": "User"
                }
            },
            "issue": {"number": 42},
            "repository": {"full_name": "test/repo"}
        }
        
        result = await comment_processor.process(payload)
        
        assert result["status"] == "ignored"
        assert result["reason"] == "No active agent task"


class TestEventProcessorErrorHandling:
    """Test error handling in event processors"""

    @pytest.fixture
    def failing_processor(self, mock_dependencies):
        """Create processor with failing dependencies"""
        github_client, job_manager, state_machine = mock_dependencies
        
        # Make job creation fail
        job_manager.create_job.side_effect = Exception("Database connection failed")
        
        return IssueEventProcessor(github_client, job_manager, state_machine)

    @pytest.mark.asyncio
    async def test_error_handling_in_processor(self, failing_processor):
        """Test that processor errors are handled gracefully"""
        payload = {
            "action": "opened",
            "issue": {
                "number": 42,
                "title": "Test Issue",
                "body": "### Task Type\n\nCode Enhancement\n\n### What would you like me to do?\n\nImplement a new feature",
                "user": {"login": "testuser"},
                "labels": [{"name": "agent:queued"}]
            },
            "repository": {
                "full_name": "test/repo"
            }
        }
        
        result = await failing_processor.process(payload)
        
        assert result["status"] == "error"
        assert "error" in result
        assert "Database connection failed" in result["error"]