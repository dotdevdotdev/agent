"""
Tests for GitHub API client
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from src.services.github_client import GitHubClient, GitHubAPIError


class TestGitHubClient:
    """Test cases for GitHub API client"""

    @pytest.fixture
    def mock_settings(self):
        """Mock settings for testing"""
        with patch('src.services.github_client.settings') as mock:
            mock.GITHUB_TOKEN = "test_token"
            mock.GITHUB_API_URL = "https://api.github.com"
            yield mock

    @pytest.fixture
    def client(self, mock_settings):
        """Create a test client"""
        return GitHubClient(token="test_token")

    def test_client_initialization(self, mock_settings):
        """Test client initialization"""
        client = GitHubClient(token="test_token")
        
        assert client.token == "test_token"
        assert "Authorization" in client.headers
        assert client.headers["Authorization"] == "token test_token"
        assert client.headers["User-Agent"] == "Agentic-GitHub-Agent/1.0"

    def test_client_no_token_raises_error(self, mock_settings):
        """Test that missing token raises ValueError"""
        mock_settings.GITHUB_TOKEN = None
        
        with pytest.raises(ValueError, match="GitHub token is required"):
            GitHubClient()

    @pytest.mark.asyncio
    async def test_agent_workflow_methods_exist(self, client):
        """Test that agent workflow methods exist"""
        # Test that the agent-specific methods exist
        assert hasattr(client, 'start_agent_task')
        assert hasattr(client, 'request_feedback')
        assert hasattr(client, 'complete_agent_task')
        assert hasattr(client, 'fail_agent_task')
        assert hasattr(client, 'update_progress')

    @pytest.mark.asyncio
    async def test_basic_operations_methods_exist(self, client):
        """Test that basic API operation methods exist"""
        # Test that basic API methods exist
        assert hasattr(client, 'get_issue')
        assert hasattr(client, 'update_issue')
        assert hasattr(client, 'create_comment')
        assert hasattr(client, 'update_comment')
        assert hasattr(client, 'get_comments')
        assert hasattr(client, 'add_labels')
        assert hasattr(client, 'remove_label')
        assert hasattr(client, 'replace_labels')
        assert hasattr(client, 'get_repository')
        assert hasattr(client, 'get_file_content')
        
        # Close the client
        await client.client.aclose()

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_settings):
        """Test client as context manager"""
        async with GitHubClient(token="test_token") as client:
            assert client.token == "test_token"
        # Client should be closed after context exit