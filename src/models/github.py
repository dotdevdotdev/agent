"""
GitHub API and webhook data models
"""

from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class GitHubUser(BaseModel):
    """GitHub user model"""

    id: int
    login: str
    avatar_url: str
    html_url: str
    type: str


class GitHubRepository(BaseModel):
    """GitHub repository model"""

    id: int
    name: str
    full_name: str
    owner: GitHubUser
    private: bool
    html_url: str
    clone_url: str
    ssh_url: str
    default_branch: str = "main"


class GitHubIssue(BaseModel):
    """GitHub issue model"""

    id: int
    number: int
    title: str
    body: Optional[str] = None
    state: str
    user: GitHubUser
    created_at: datetime
    updated_at: datetime
    html_url: str
    labels: list[Dict[str, Any]] = []
    assignees: list[GitHubUser] = []


class GitHubWebhookPayload(BaseModel):
    """GitHub webhook payload for issue events"""

    action: str
    issue: GitHubIssue
    repository: GitHubRepository
    sender: GitHubUser

    class Config:
        extra = "allow"  # Allow additional fields from GitHub


class GitHubIssueComment(BaseModel):
    """GitHub issue comment model"""

    id: int
    body: str
    user: GitHubUser
    created_at: datetime
    updated_at: datetime
    html_url: str
