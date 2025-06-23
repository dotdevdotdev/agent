"""
Tests for Git Service
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch

from src.services.git_service import GitService, GitServiceError, WorktreeInfo


class TestGitService:
    """Test cases for GitService"""

    def test_initialization_error_handling(self):
        """Test GitService handles invalid repositories gracefully"""
        with tempfile.TemporaryDirectory() as temp_dir:
            non_git_dir = Path(temp_dir) / "not_a_git_repo"
            non_git_dir.mkdir()
            
            with pytest.raises(GitServiceError, match="Invalid git repository"):
                GitService(base_repo_path=str(non_git_dir))

    def test_worktree_base_path_creation(self):
        """Test that worktree base path is created"""
        with tempfile.TemporaryDirectory() as temp_dir:
            worktree_base = Path(temp_dir) / "worktrees"
            
            # Mock the base repo initialization to avoid git dependency
            with patch('src.services.git_service.Repo') as mock_repo:
                mock_instance = mock_repo.return_value
                mock_instance.bare = False
                mock_instance.active_branch.name = "master"
                
                service = GitService(
                    base_repo_path=temp_dir,
                    worktree_base_path=worktree_base
                )
                
                assert worktree_base.exists()
                assert service.worktree_base_path == worktree_base

    def test_get_repository_info_success(self):
        """Test repository info returns expected data"""
        with patch('src.services.git_service.Repo') as mock_repo:
            mock_instance = mock_repo.return_value
            mock_instance.bare = False
            mock_instance.active_branch.name = "master"
            mock_instance.head.commit.hexsha = "abc123"
            mock_instance.remotes = []
            mock_instance.is_dirty.return_value = False
            mock_instance.untracked_files = []
            
            service = GitService()
            info = service.get_repository_info()
            
            assert "current_branch" in info
            assert "head_commit" in info
            assert info["current_branch"] == "master"

    def test_active_worktrees_tracking(self):
        """Test that active worktrees are tracked correctly"""
        with patch('src.services.git_service.Repo') as mock_repo:
            mock_instance = mock_repo.return_value
            mock_instance.bare = False
            mock_instance.active_branch.name = "master"
            
            service = GitService()
            
            # Should start with no active worktrees
            assert len(service.list_active_worktrees()) == 0
            assert service.get_worktree_info("nonexistent") is None

    def test_worktree_stats(self):
        """Test worktree statistics calculation"""
        with patch('src.services.git_service.Repo') as mock_repo:
            mock_instance = mock_repo.return_value
            mock_instance.bare = False
            mock_instance.active_branch.name = "master"
            
            service = GitService()
            stats = service.get_worktree_stats()
            
            assert "active_worktrees" in stats
            assert "base_path" in stats
            assert "total_disk_usage_bytes" in stats
            assert "worktree_details" in stats
            assert stats["active_worktrees"] == 0


if __name__ == "__main__":
    pytest.main([__file__])