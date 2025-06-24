"""
Application settings and configuration
"""

import os
from pathlib import Path
from typing import Optional, List

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Server Configuration
    HOST: str = Field(default="0.0.0.0", description="Server host")
    PORT: int = Field(default=8080, description="Server port")
    DEBUG: bool = Field(default=False, description="Debug mode")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    # GitHub Configuration
    GITHUB_WEBHOOK_SECRET: str = Field(..., description="GitHub webhook secret")
    GITHUB_TOKEN: str = Field(..., description="GitHub personal access token")
    GITHUB_API_URL: str = Field(
        default="https://api.github.com", description="GitHub API URL"
    )

    # Repository Configuration
    REPO_OWNER: str = Field(..., description="GitHub repository owner")
    REPO_NAME: str = Field(..., description="GitHub repository name")
    WORKTREE_BASE_PATH: Path = Field(
        default=Path("./worktrees"), description="Base path for git worktrees"
    )

    # Claude CLI Configuration
    CLAUDE_CODE_PATH: str = Field(
        default="claude", description="Path to claude CLI tool"
    )
    CLAUDE_TIMEOUT: int = Field(
        default=3600, description="Claude execution timeout in seconds"
    )

    # Job Management
    MAX_CONCURRENT_JOBS: int = Field(default=3, description="Maximum concurrent jobs")
    JOB_TIMEOUT: int = Field(default=7200, description="Job timeout in seconds")

    # Admin Configuration
    ADMIN_USERS: str = Field(
        default="", description="Comma-separated list of GitHub usernames with admin privileges"
    )
    
    # Validation Configuration
    GENERAL_QUESTION_MIN_SCORE: int = Field(
        default=30, description="Minimum validation score for general questions"
    )
    STANDARD_MIN_SCORE: int = Field(
        default=50, description="Minimum validation score for code-related tasks"
    )

    @property
    def admin_users_list(self) -> List[str]:
        """Get admin users as a list"""
        if not self.ADMIN_USERS:
            return []
        return [user.strip() for user in self.ADMIN_USERS.split(",") if user.strip()]
    
    def is_admin_user(self, username: str) -> bool:
        """Check if a user is an admin"""
        return username in self.admin_users_list

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Global settings instance
settings = Settings()
