"""
Git service for repository and worktree management
"""

import os
import shutil
import structlog
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime

import git
from git import Repo, GitCommandError, InvalidGitRepositoryError

from config.settings import settings

logger = structlog.get_logger()


@dataclass
class WorktreeInfo:
    """Information about a git worktree"""
    path: Path
    branch: str
    commit_hash: str
    created_at: datetime
    job_id: str
    repository: str
    issue_number: int


class GitServiceError(Exception):
    """Custom exception for git service errors"""
    def __init__(self, message: str, command: str = None, return_code: int = None):
        self.message = message
        self.command = command
        self.return_code = return_code
        super().__init__(message)


class GitService:
    """Service for managing git operations and worktrees"""

    def __init__(self, base_repo_path: str = None, worktree_base_path: Path = None):
        self.base_repo_path = base_repo_path or os.getcwd()
        self.worktree_base_path = worktree_base_path or settings.WORKTREE_BASE_PATH
        self.active_worktrees: Dict[str, WorktreeInfo] = {}
        
        # Ensure worktree base directory exists
        self.worktree_base_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize base repository
        self.base_repo = None
        self._initialize_base_repo()

    def _initialize_base_repo(self) -> None:
        """Initialize the base repository"""
        try:
            self.base_repo = Repo(self.base_repo_path)
            if self.base_repo.bare:
                raise GitServiceError("Base repository cannot be bare")
                
            logger.info(
                "Git service initialized",
                repo_path=self.base_repo_path,
                current_branch=self.base_repo.active_branch.name,
                worktree_base=str(self.worktree_base_path)
            )
        except InvalidGitRepositoryError:
            raise GitServiceError(f"Invalid git repository at {self.base_repo_path}")
        except Exception as e:
            raise GitServiceError(f"Failed to initialize git repository: {str(e)}")

    def get_repository_info(self) -> Dict[str, Any]:
        """Get information about the base repository"""
        try:
            return {
                "path": self.base_repo_path,
                "current_branch": self.base_repo.active_branch.name,
                "head_commit": self.base_repo.head.commit.hexsha,
                "remote_url": self.base_repo.remotes.origin.url if self.base_repo.remotes else None,
                "is_dirty": self.base_repo.is_dirty(),
                "untracked_files": self.base_repo.untracked_files
            }
        except Exception as e:
            logger.error("Failed to get repository info", error=str(e))
            raise GitServiceError(f"Failed to get repository info: {str(e)}")

    def create_worktree(self, job_id: str, repository: str, issue_number: int, 
                       branch_name: str = None) -> WorktreeInfo:
        """Create a new git worktree for isolated processing"""
        if job_id in self.active_worktrees:
            raise GitServiceError(f"Worktree already exists for job {job_id}")

        try:
            # Generate worktree path
            worktree_dir = self.worktree_base_path / f"job-{job_id}"
            if worktree_dir.exists():
                shutil.rmtree(worktree_dir)
            
            # Create branch name if not provided
            if not branch_name:
                branch_name = f"agent/job-{job_id}"
            
            # Ensure we're on the main branch
            self.base_repo.git.checkout('master')
            
            # Create and checkout new branch
            try:
                # Delete branch if it exists
                self.base_repo.git.branch('-D', branch_name)
            except GitCommandError:
                pass  # Branch doesn't exist, which is fine
                
            new_branch = self.base_repo.create_head(branch_name)
            
            # Create worktree
            self.base_repo.git.worktree('add', str(worktree_dir), branch_name)
            
            # Get worktree repository object
            worktree_repo = Repo(worktree_dir)
            commit_hash = worktree_repo.head.commit.hexsha
            
            # Create worktree info
            worktree_info = WorktreeInfo(
                path=worktree_dir,
                branch=branch_name,
                commit_hash=commit_hash,
                created_at=datetime.now(),
                job_id=job_id,
                repository=repository,
                issue_number=issue_number
            )
            
            self.active_worktrees[job_id] = worktree_info
            
            logger.info(
                "Worktree created",
                job_id=job_id,
                path=str(worktree_dir),
                branch=branch_name,
                commit=commit_hash[:8]
            )
            
            return worktree_info
            
        except GitCommandError as e:
            logger.error("Git command failed during worktree creation", error=str(e))
            raise GitServiceError(f"Git command failed: {str(e)}", command=str(e.command))
        except Exception as e:
            logger.error("Failed to create worktree", job_id=job_id, error=str(e))
            raise GitServiceError(f"Failed to create worktree: {str(e)}")

    def cleanup_worktree(self, job_id: str) -> bool:
        """Clean up a worktree and remove it"""
        if job_id not in self.active_worktrees:
            logger.warning("Worktree not found for cleanup", job_id=job_id)
            return False

        worktree_info = self.active_worktrees[job_id]
        
        try:
            # Remove worktree
            if worktree_info.path.exists():
                self.base_repo.git.worktree('remove', str(worktree_info.path), '--force')
            
            # Delete the branch
            try:
                self.base_repo.git.branch('-D', worktree_info.branch)
            except GitCommandError:
                logger.warning("Failed to delete branch", branch=worktree_info.branch)
            
            # Remove from active worktrees
            del self.active_worktrees[job_id]
            
            logger.info(
                "Worktree cleaned up",
                job_id=job_id,
                path=str(worktree_info.path),
                branch=worktree_info.branch
            )
            
            return True
            
        except GitCommandError as e:
            logger.error("Git command failed during worktree cleanup", job_id=job_id, error=str(e))
            return False
        except Exception as e:
            logger.error("Failed to cleanup worktree", job_id=job_id, error=str(e))
            return False

    def get_worktree_info(self, job_id: str) -> Optional[WorktreeInfo]:
        """Get information about a specific worktree"""
        return self.active_worktrees.get(job_id)

    def list_active_worktrees(self) -> List[WorktreeInfo]:
        """List all active worktrees"""
        return list(self.active_worktrees.values())

    def cleanup_all_worktrees(self) -> Dict[str, bool]:
        """Clean up all active worktrees (useful for shutdown)"""
        results = {}
        job_ids = list(self.active_worktrees.keys())
        
        for job_id in job_ids:
            results[job_id] = self.cleanup_worktree(job_id)
        
        logger.info("All worktrees cleanup completed", results=results)
        return results

    def get_file_content(self, job_id: str, file_path: str) -> Optional[str]:
        """Get content of a file from a worktree"""
        if job_id not in self.active_worktrees:
            return None
            
        worktree_info = self.active_worktrees[job_id]
        full_path = worktree_info.path / file_path
        
        try:
            if full_path.exists() and full_path.is_file():
                return full_path.read_text(encoding='utf-8')
        except Exception as e:
            logger.error("Failed to read file", file_path=file_path, error=str(e))
        
        return None

    def list_files(self, job_id: str, pattern: str = "**/*") -> List[str]:
        """List files in a worktree matching a pattern"""
        if job_id not in self.active_worktrees:
            return []
            
        worktree_info = self.active_worktrees[job_id]
        
        try:
            files = []
            for file_path in worktree_info.path.glob(pattern):
                if file_path.is_file():
                    # Return relative path from worktree root
                    rel_path = file_path.relative_to(worktree_info.path)
                    files.append(str(rel_path))
            return sorted(files)
        except Exception as e:
            logger.error("Failed to list files", job_id=job_id, error=str(e))
            return []

    def commit_changes(self, job_id: str, message: str, author_name: str = "Agent", 
                      author_email: str = "agent@example.com") -> Optional[str]:
        """Commit changes in a worktree"""
        if job_id not in self.active_worktrees:
            return None
            
        worktree_info = self.active_worktrees[job_id]
        
        try:
            worktree_repo = Repo(worktree_info.path)
            
            # Add all changes
            worktree_repo.git.add(A=True)
            
            # Check if there are changes to commit
            if not worktree_repo.is_dirty(untracked_files=True):
                logger.info("No changes to commit", job_id=job_id)
                return None
            
            # Commit changes
            commit = worktree_repo.index.commit(
                message,
                author=git.Actor(author_name, author_email),
                committer=git.Actor(author_name, author_email)
            )
            
            logger.info(
                "Changes committed",
                job_id=job_id,
                commit=commit.hexsha[:8],
                message=message
            )
            
            return commit.hexsha
            
        except Exception as e:
            logger.error("Failed to commit changes", job_id=job_id, error=str(e))
            return None

    def get_worktree_stats(self) -> Dict[str, Any]:
        """Get statistics about worktree usage"""
        total_size = 0
        for worktree_info in self.active_worktrees.values():
            if worktree_info.path.exists():
                total_size += sum(f.stat().st_size for f in worktree_info.path.rglob('*') if f.is_file())
        
        return {
            "active_worktrees": len(self.active_worktrees),
            "base_path": str(self.worktree_base_path),
            "total_disk_usage_bytes": total_size,
            "total_disk_usage_mb": total_size / (1024 * 1024),
            "worktree_details": [
                {
                    "job_id": info.job_id,
                    "repository": info.repository,
                    "issue_number": info.issue_number,
                    "branch": info.branch,
                    "created_at": info.created_at.isoformat(),
                    "path": str(info.path)
                }
                for info in self.active_worktrees.values()
            ]
        }