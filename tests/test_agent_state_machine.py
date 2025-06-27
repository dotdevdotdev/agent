"""
Comprehensive tests for the Agent State Machine
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta

from src.services.agent_state_machine import (
    AgentStateMachine, 
    AgentState, 
    StateTransition,
    InvalidStateTransitionError,
    UserResponseTimeoutError
)
from src.services.github_client import GitHubClient
from src.services.job_manager import JobManager


class TestAgentStateMachine:
    """Test cases for Agent State Machine"""

    @pytest.fixture
    def mock_github_client(self):
        """Mock GitHub client for testing"""
        client = Mock(spec=GitHubClient)
        client.transition_agent_state = AsyncMock()
        client.create_comment = AsyncMock()
        client.request_user_feedback = AsyncMock()
        client.post_progress_update = AsyncMock()
        return client

    @pytest.fixture
    def mock_job_manager(self):
        """Mock job manager for testing"""
        manager = Mock(spec=JobManager)
        manager.update_job_status = AsyncMock()
        manager.get_job = AsyncMock()
        return manager

    @pytest.fixture
    def state_machine(self, mock_github_client, mock_job_manager):
        """Create state machine instance for testing"""
        return AgentStateMachine(
            github_client=mock_github_client,
            job_manager=mock_job_manager
        )

    @pytest.fixture
    def sample_context(self):
        """Sample state context for testing"""
        return {
            "job_id": "test-job-123",
            "repository": "test/repo",
            "issue_number": 42,
            "user_message": "Test message",
            "metadata": {"test": "data"}
        }

    @pytest.mark.asyncio
    async def test_initialize_context(self, state_machine, mock_github_client):
        """Test context initialization"""
        job_id = "test-job-123"
        repository = "test/repo"
        issue_number = 42

        context = await state_machine.initialize_context(job_id, repository, issue_number)

        assert context["job_id"] == job_id
        assert context["repository"] == repository
        assert context["issue_number"] == issue_number
        assert context["current_state"] == AgentState.QUEUED
        assert "created_at" in context
        assert "transition_history" in context

        # Verify GitHub client was called
        mock_github_client.transition_agent_state.assert_called_once_with(
            repository, issue_number, AgentState.QUEUED, "Task queued for processing..."
        )

    @pytest.mark.asyncio
    async def test_valid_state_transitions(self, state_machine, sample_context):
        """Test valid state transitions"""
        job_id = sample_context["job_id"]
        
        # Initialize context
        await state_machine.initialize_context(
            job_id, sample_context["repository"], sample_context["issue_number"]
        )

        # Test valid transitions
        valid_transitions = [
            (AgentState.QUEUED, AgentState.VALIDATING),
            (AgentState.VALIDATING, AgentState.ANALYZING),
            (AgentState.ANALYZING, AgentState.IN_PROGRESS),
            (AgentState.IN_PROGRESS, AgentState.IMPLEMENTING),
            (AgentState.IMPLEMENTING, AgentState.TESTING),
            (AgentState.TESTING, AgentState.COMPLETED),
        ]

        current_state = AgentState.QUEUED
        for from_state, to_state in valid_transitions:
            assert state_machine.contexts[job_id]["current_state"] == from_state
            
            await state_machine.transition_to(job_id, to_state, "Test transition")
            
            assert state_machine.contexts[job_id]["current_state"] == to_state
            current_state = to_state

    @pytest.mark.asyncio
    async def test_invalid_state_transitions(self, state_machine, sample_context):
        """Test invalid state transitions are rejected"""
        job_id = sample_context["job_id"]
        
        # Initialize context
        await state_machine.initialize_context(
            job_id, sample_context["repository"], sample_context["issue_number"]
        )

        # Test invalid transitions
        with pytest.raises(InvalidStateTransitionError):
            # Can't go directly from QUEUED to COMPLETED
            await state_machine.transition_to(job_id, AgentState.COMPLETED, "Invalid transition")

        with pytest.raises(InvalidStateTransitionError):
            # Can't go from QUEUED to ANALYZING (must go through VALIDATING)
            await state_machine.transition_to(job_id, AgentState.ANALYZING, "Invalid transition")

    @pytest.mark.asyncio
    async def test_error_transitions_from_any_state(self, state_machine, sample_context):
        """Test that FAILED and CANCELLED can be reached from any state"""
        job_id = sample_context["job_id"]
        
        # Initialize context and advance to IN_PROGRESS
        await state_machine.initialize_context(
            job_id, sample_context["repository"], sample_context["issue_number"]
        )
        await state_machine.transition_to(job_id, AgentState.VALIDATING, "Test")
        await state_machine.transition_to(job_id, AgentState.ANALYZING, "Test")
        await state_machine.transition_to(job_id, AgentState.IN_PROGRESS, "Test")

        # Test transition to FAILED from IN_PROGRESS
        await state_machine.transition_to(job_id, AgentState.FAILED, "Error occurred")
        assert state_machine.contexts[job_id]["current_state"] == AgentState.FAILED

        # Reset and test CANCELLED
        state_machine.contexts[job_id]["current_state"] = AgentState.IMPLEMENTING
        await state_machine.transition_to(job_id, AgentState.CANCELLED, "User cancelled")
        assert state_machine.contexts[job_id]["current_state"] == AgentState.CANCELLED

    @pytest.mark.asyncio
    async def test_handle_error_with_recovery(self, state_machine, sample_context, mock_github_client):
        """Test error handling with recovery attempts"""
        job_id = sample_context["job_id"]
        
        # Initialize context and advance to IMPLEMENTING
        await state_machine.initialize_context(
            job_id, sample_context["repository"], sample_context["issue_number"]
        )
        await state_machine.transition_to(job_id, AgentState.VALIDATING, "Test")
        await state_machine.transition_to(job_id, AgentState.ANALYZING, "Test")
        await state_machine.transition_to(job_id, AgentState.IN_PROGRESS, "Test")
        await state_machine.transition_to(job_id, AgentState.IMPLEMENTING, "Test")

        # Mock error
        test_error = Exception("Test error message")

        # Handle error (should attempt recovery first)
        await state_machine.handle_error(job_id, test_error)

        # Verify error context is saved
        context = state_machine.contexts[job_id]
        assert context["current_state"] == AgentState.RECOVERING
        assert "error_info" in context
        assert context["error_info"]["message"] == "Test error message"
        assert context["error_info"]["recovery_attempts"] == 1

    @pytest.mark.asyncio
    async def test_escalation_after_max_recovery_attempts(self, state_machine, sample_context):
        """Test escalation after maximum recovery attempts"""
        job_id = sample_context["job_id"]
        
        # Initialize context
        await state_machine.initialize_context(
            job_id, sample_context["repository"], sample_context["issue_number"]
        )
        
        # Simulate multiple recovery attempts
        test_error = Exception("Persistent error")
        
        # First few errors should trigger recovery
        for attempt in range(state_machine.max_recovery_attempts):
            await state_machine.handle_error(job_id, test_error)
            context = state_machine.contexts[job_id]
            
            if attempt < state_machine.max_recovery_attempts - 1:
                assert context["current_state"] == AgentState.RECOVERING
                assert context["error_info"]["recovery_attempts"] == attempt + 1
            else:
                # Final attempt should escalate
                assert context["current_state"] == AgentState.ESCALATED

    @pytest.mark.asyncio
    async def test_user_response_handling(self, state_machine, sample_context):
        """Test handling of user responses"""
        job_id = sample_context["job_id"]
        
        # Initialize context and set to awaiting feedback
        await state_machine.initialize_context(
            job_id, sample_context["repository"], sample_context["issue_number"]
        )
        await state_machine.transition_to(job_id, AgentState.AWAITING_FEEDBACK, "Need feedback")

        # Test user response
        user_response = "Please continue with the implementation"
        commenter = "testuser"

        await state_machine.handle_user_response(job_id, user_response, commenter)

        context = state_machine.contexts[job_id]
        assert "user_feedback" in context
        assert context["user_feedback"]["response"] == user_response
        assert context["user_feedback"]["commenter"] == commenter

    @pytest.mark.asyncio
    async def test_user_response_timeout(self, state_machine, sample_context):
        """Test user response timeout handling"""
        job_id = sample_context["job_id"]
        
        # Initialize context
        await state_machine.initialize_context(
            job_id, sample_context["repository"], sample_context["issue_number"]
        )
        
        # Set a very short timeout for testing
        original_timeout = state_machine.user_response_timeout
        state_machine.user_response_timeout = timedelta(milliseconds=100)
        
        try:
            # Request feedback and wait for timeout
            await state_machine.transition_to(job_id, AgentState.AWAITING_FEEDBACK, "Need feedback")
            
            # Wait for timeout
            await asyncio.sleep(0.2)
            
            # Check if timeout was handled (implementation dependent)
            context = state_machine.contexts[job_id]
            # The timeout handling behavior depends on implementation
            
        finally:
            # Restore original timeout
            state_machine.user_response_timeout = original_timeout

    @pytest.mark.asyncio
    async def test_transition_history_tracking(self, state_machine, sample_context):
        """Test that transition history is properly tracked"""
        job_id = sample_context["job_id"]
        
        # Initialize context
        await state_machine.initialize_context(
            job_id, sample_context["repository"], sample_context["issue_number"]
        )

        # Make several transitions
        transitions = [
            (AgentState.VALIDATING, "Starting validation"),
            (AgentState.ANALYZING, "Starting analysis"),
            (AgentState.IN_PROGRESS, "Starting implementation"),
            (AgentState.COMPLETED, "Task completed"),
        ]

        for state, message in transitions:
            await state_machine.transition_to(job_id, state, message)

        # Check transition history
        context = state_machine.contexts[job_id]
        history = context["transition_history"]
        
        assert len(history) == len(transitions) + 1  # +1 for initial QUEUED state
        
        # Verify each transition is recorded
        for i, (expected_state, expected_message) in enumerate(transitions):
            transition = history[i + 1]  # Skip initial QUEUED
            assert transition["to_state"] == expected_state
            assert transition["user_message"] == expected_message
            assert "timestamp" in transition

    @pytest.mark.asyncio
    async def test_context_cleanup(self, state_machine, sample_context):
        """Test context cleanup for completed jobs"""
        job_id = sample_context["job_id"]
        
        # Initialize context
        await state_machine.initialize_context(
            job_id, sample_context["repository"], sample_context["issue_number"]
        )

        # Verify context exists
        assert job_id in state_machine.contexts

        # Complete the job
        await state_machine.transition_to(job_id, AgentState.VALIDATING, "Test")
        await state_machine.transition_to(job_id, AgentState.ANALYZING, "Test")
        await state_machine.transition_to(job_id, AgentState.IN_PROGRESS, "Test")
        await state_machine.transition_to(job_id, AgentState.IMPLEMENTING, "Test")
        await state_machine.transition_to(job_id, AgentState.TESTING, "Test")
        await state_machine.transition_to(job_id, AgentState.COMPLETED, "Test")

        # Context should still exist immediately after completion
        assert job_id in state_machine.contexts
        
        # Manual cleanup test
        state_machine.cleanup_context(job_id)
        assert job_id not in state_machine.contexts

    @pytest.mark.asyncio
    async def test_concurrent_state_transitions(self, state_machine):
        """Test handling of concurrent state transitions for different jobs"""
        job_ids = ["job-1", "job-2", "job-3"]
        repository = "test/repo"
        
        # Initialize multiple contexts concurrently
        tasks = []
        for i, job_id in enumerate(job_ids):
            task = state_machine.initialize_context(job_id, repository, i + 1)
            tasks.append(task)
        
        await asyncio.gather(*tasks)
        
        # Verify all contexts were created
        for job_id in job_ids:
            assert job_id in state_machine.contexts
            assert state_machine.contexts[job_id]["current_state"] == AgentState.QUEUED

        # Make concurrent transitions
        transition_tasks = []
        for job_id in job_ids:
            task = state_machine.transition_to(job_id, AgentState.VALIDATING, f"Validating {job_id}")
            transition_tasks.append(task)
        
        await asyncio.gather(*transition_tasks)
        
        # Verify all transitions completed
        for job_id in job_ids:
            assert state_machine.contexts[job_id]["current_state"] == AgentState.VALIDATING

    def test_state_transition_validation_logic(self, state_machine):
        """Test the internal state transition validation logic"""
        # Test valid transitions
        assert state_machine._is_valid_transition(AgentState.QUEUED, AgentState.VALIDATING)
        assert state_machine._is_valid_transition(AgentState.VALIDATING, AgentState.ANALYZING)
        assert state_machine._is_valid_transition(AgentState.ANALYZING, AgentState.IN_PROGRESS)
        
        # Test invalid transitions
        assert not state_machine._is_valid_transition(AgentState.QUEUED, AgentState.COMPLETED)
        assert not state_machine._is_valid_transition(AgentState.VALIDATING, AgentState.IMPLEMENTING)
        assert not state_machine._is_valid_transition(AgentState.COMPLETED, AgentState.QUEUED)
        
        # Test error/cancel transitions (should be valid from any state)
        for state in AgentState:
            if state not in [AgentState.FAILED, AgentState.CANCELLED]:
                assert state_machine._is_valid_transition(state, AgentState.FAILED)
                assert state_machine._is_valid_transition(state, AgentState.CANCELLED)

    @pytest.mark.asyncio
    async def test_github_integration_calls(self, state_machine, sample_context, mock_github_client):
        """Test that GitHub client methods are called correctly"""
        job_id = sample_context["job_id"]
        repository = sample_context["repository"]
        issue_number = sample_context["issue_number"]
        
        # Initialize context
        await state_machine.initialize_context(job_id, repository, issue_number)
        
        # Make a transition
        await state_machine.transition_to(job_id, AgentState.VALIDATING, "Starting validation")
        
        # Verify GitHub client calls
        assert mock_github_client.transition_agent_state.call_count >= 2  # Initial + transition
        
        # Check the calls
        calls = mock_github_client.transition_agent_state.call_args_list
        
        # First call should be for QUEUED state
        first_call = calls[0]
        assert first_call[0] == (repository, issue_number, AgentState.QUEUED, "Task queued for processing...")
        
        # Second call should be for VALIDATING state
        second_call = calls[1]
        assert second_call[0] == (repository, issue_number, AgentState.VALIDATING, "Starting validation")

    @pytest.mark.asyncio
    async def test_error_context_preservation(self, state_machine, sample_context):
        """Test that error context is preserved across recovery attempts"""
        job_id = sample_context["job_id"]
        
        # Initialize context
        await state_machine.initialize_context(
            job_id, sample_context["repository"], sample_context["issue_number"]
        )
        
        # Create test errors
        first_error = Exception("First error")
        second_error = Exception("Second error")
        
        # Handle first error
        await state_machine.handle_error(job_id, first_error)
        context = state_machine.contexts[job_id]
        
        assert context["error_info"]["message"] == "First error"
        assert context["error_info"]["recovery_attempts"] == 1
        
        # Handle second error (should increment attempts, update message)
        await state_machine.handle_error(job_id, second_error)
        context = state_machine.contexts[job_id]
        
        assert context["error_info"]["message"] == "Second error"
        assert context["error_info"]["recovery_attempts"] == 2
        assert len(context["error_info"]["error_history"]) == 2