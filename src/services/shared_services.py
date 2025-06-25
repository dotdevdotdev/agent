"""
Shared service instances to prevent multiple initialization issues
"""

from .job_manager import JobManager
from .github_client import GitHubClient
from .agent_state_machine import AgentStateMachine

# Global shared instances - initialized once
_job_manager = None
_github_client = None
_state_machine = None
_event_router = None

def get_job_manager() -> JobManager:
    """Get shared JobManager instance"""
    global _job_manager
    if _job_manager is None:
        _job_manager = JobManager()
    return _job_manager

def get_github_client() -> GitHubClient:
    """Get shared GitHubClient instance"""
    global _github_client
    if _github_client is None:
        _github_client = GitHubClient()
    return _github_client

def get_state_machine() -> AgentStateMachine:
    """Get shared AgentStateMachine instance"""
    global _state_machine
    if _state_machine is None:
        github_client = get_github_client()
        job_manager = get_job_manager()
        _state_machine = AgentStateMachine(github_client, job_manager)
    return _state_machine

def get_event_router():
    """Get shared EventRouter instance"""
    global _event_router
    if _event_router is None:
        from .event_router import EventRouter
        github_client = get_github_client()
        job_manager = get_job_manager()
        state_machine = get_state_machine()
        _event_router = EventRouter(github_client, job_manager, state_machine)
    return _event_router

def reset_services():
    """Reset all shared services (for testing)"""
    global _job_manager, _github_client, _state_machine, _event_router
    _job_manager = None
    _github_client = None
    _state_machine = None
    _event_router = None