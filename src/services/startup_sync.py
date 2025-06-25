"""
Startup synchronization service for recovering jobs and syncing with GitHub
"""

import asyncio
import structlog
from typing import List, Dict, Any, Optional
from datetime import datetime

from config.settings import settings
from .github_client import GitHubClient
from .job_manager import JobManager
from .agent_state_machine import AgentStateMachine, AgentState
from .event_router import IssueEventProcessor
from .issue_parser import IssueParser
from .task_validator import TaskValidator

logger = structlog.get_logger()


class StartupSyncService:
    """Handles startup synchronization between GitHub state and local jobs"""

    def __init__(self, github_client: GitHubClient, job_manager: JobManager, 
                 state_machine: AgentStateMachine):
        self.github_client = github_client
        self.job_manager = job_manager
        self.state_machine = state_machine
        self.issue_parser = IssueParser()
        self.task_validator = TaskValidator()

    async def sync_on_startup(self) -> Dict[str, Any]:
        """
        Synchronize with GitHub on startup:
        1. Get all agent issues from GitHub
        2. Check for orphaned jobs (local jobs without GitHub state)
        3. Check for orphaned GitHub states (GitHub labels without local jobs)
        4. Recover/restart jobs as needed
        """
        logger.info("Starting startup synchronization with GitHub")
        
        repo_full_name = f"{settings.REPO_OWNER}/{settings.REPO_NAME}"
        sync_results = {
            "github_issues_found": 0,
            "jobs_recovered": 0,
            "jobs_restarted": 0,
            "orphaned_github_states": 0,
            "orphaned_local_jobs": 0,
            "errors": []
        }

        try:
            # Step 1: Get all agent issues from GitHub
            github_issues = await self.github_client.get_agent_issues(repo_full_name, state="open")
            sync_results["github_issues_found"] = len(github_issues)
            
            # Step 2: Get current local jobs
            local_jobs = await self.job_manager.list_jobs()
            active_local_jobs = [j for j in local_jobs if j.status in ['pending', 'running']]
            
            # Step 3: Sync GitHub issues with local jobs
            for issue in github_issues:
                try:
                    await self._sync_github_issue(issue, sync_results)
                except Exception as e:
                    error_msg = f"Failed to sync issue #{issue.get('number')}: {str(e)}"
                    sync_results["errors"].append(error_msg)
                    logger.error("Issue sync failed", issue=issue.get('number'), error=str(e))

            # Step 4: Check for orphaned local jobs
            await self._check_orphaned_local_jobs(active_local_jobs, github_issues, sync_results)

            logger.info(
                "Startup synchronization completed",
                **{k: v for k, v in sync_results.items() if k != "errors"}
            )

            if sync_results["errors"]:
                logger.warning(f"Synchronization completed with {len(sync_results['errors'])} errors")

            return sync_results

        except Exception as e:
            logger.error("Startup synchronization failed", error=str(e))
            sync_results["errors"].append(f"Sync failed: {str(e)}")
            return sync_results

    async def _sync_github_issue(self, github_issue: Dict[str, Any], sync_results: Dict[str, Any]) -> None:
        """Sync a single GitHub issue with local job state"""
        issue_number = github_issue["number"]
        repo_full_name = f"{settings.REPO_OWNER}/{settings.REPO_NAME}"
        
        # Get current agent state from GitHub labels
        agent_state = await self.github_client.get_current_agent_state(repo_full_name, issue_number)
        
        if not agent_state:
            logger.debug(f"Issue #{issue_number} has no agent state, skipping")
            return

        # Check if we have a local job for this issue
        local_job = await self._find_local_job_for_issue(issue_number)
        
        if not local_job:
            # Orphaned GitHub state - has agent label but no local job
            await self._handle_orphaned_github_state(github_issue, agent_state, sync_results)
        else:
            # Job exists - check if it needs recovery
            await self._handle_existing_job_recovery(local_job, agent_state, sync_results)

    async def _find_local_job_for_issue(self, issue_number: int) -> Optional[Any]:
        """Find local job for given issue number"""
        repo_full_name = f"{settings.REPO_OWNER}/{settings.REPO_NAME}"
        local_jobs = await self.job_manager.list_jobs()
        
        for job in local_jobs:
            if (job.repository_full_name == repo_full_name and 
                job.issue_number == issue_number and
                job.status in ['pending', 'running']):
                return job
        return None

    async def _handle_orphaned_github_state(self, github_issue: Dict[str, Any], 
                                          agent_state: str, sync_results: Dict[str, Any]) -> None:
        """Handle GitHub issue with agent state but no local job"""
        issue_number = github_issue["number"]
        sync_results["orphaned_github_states"] += 1
        
        logger.info(
            "Found orphaned GitHub state, restarting job",
            issue=issue_number,
            github_state=agent_state
        )

        # Determine if we should restart based on the state
        if agent_state in ['agent:queued', 'agent:in-progress', 'agent:validating', 'agent:analyzing']:
            # Create new job to restart processing
            await self._restart_job_from_github_issue(github_issue, sync_results)
        elif agent_state == 'agent:awaiting-feedback':
            # Job is waiting for user input - don't restart automatically
            logger.info(f"Issue #{issue_number} is awaiting feedback, not restarting")
        else:
            # Completed, failed, cancelled states - clean up if needed
            logger.info(f"Issue #{issue_number} is in final state {agent_state}, no action needed")

    async def _restart_job_from_github_issue(self, github_issue: Dict[str, Any], 
                                           sync_results: Dict[str, Any]) -> None:
        """Restart job from GitHub issue data"""
        try:
            issue_number = github_issue["number"]
            issue_title = github_issue["title"]
            issue_body = github_issue.get("body", "")
            repo_full_name = f"{settings.REPO_OWNER}/{settings.REPO_NAME}"

            # Check for existing worktree from previous interrupted job
            existing_worktree_info = await self._check_existing_worktree(issue_number)

            # Parse and validate the issue
            issue_author = github_issue.get('user', {}).get('login', '')
            parsed_task = self.issue_parser.parse_issue(issue_body, issue_title, issue_author)
            validation_result = self.task_validator.validate_task_completeness(parsed_task)

            # Create new job
            from src.models.jobs import JobCreate
            job_create = JobCreate(
                issue_number=issue_number,
                repository_full_name=repo_full_name,
                issue_title=issue_title,
                issue_body=issue_body,
                metadata={
                    'parsed_task': parsed_task.__dict__,
                    'validation_result': validation_result,
                    'restarted_from_sync': True,
                    'existing_worktree_info': existing_worktree_info
                }
            )

            job = await self.job_manager.create_job(job_create)

            # Initialize state machine context
            await self.state_machine.initialize_context(job.job_id, repo_full_name, issue_number)

            # Start processing
            await self.state_machine.transition_to(
                job.job_id, AgentState.VALIDATING,
                user_message="Job restarted from startup sync..."
            )

            # Schedule the actual processing
            from .processing_orchestrator import ProcessingOrchestrator
            orchestrator = ProcessingOrchestrator(
                github_client=self.github_client,
                state_machine=self.state_machine
            )
            asyncio.create_task(orchestrator.process_task(job.job_id, parsed_task))

            sync_results["jobs_restarted"] += 1
            logger.info("Job restarted successfully", job_id=job.job_id, issue=issue_number)

        except Exception as e:
            error_msg = f"Failed to restart job for issue #{github_issue['number']}: {str(e)}"
            sync_results["errors"].append(error_msg)
            logger.error("Job restart failed", issue=github_issue["number"], error=str(e))

    async def _handle_existing_job_recovery(self, local_job: Any, agent_state: str, 
                                          sync_results: Dict[str, Any]) -> None:
        """Handle recovery of existing local job"""
        # For now, just log that the job exists
        # In the future, we could check if the job is stuck and needs recovery
        logger.info(
            "Local job exists for GitHub issue",
            job_id=local_job.job_id,
            issue=local_job.issue_number,
            local_status=local_job.status,
            github_state=agent_state
        )
        sync_results["jobs_recovered"] += 1

    async def _check_orphaned_local_jobs(self, local_jobs: List[Any], 
                                       github_issues: List[Dict[str, Any]], 
                                       sync_results: Dict[str, Any]) -> None:
        """Check for local jobs that don't have corresponding GitHub issues"""
        github_issue_numbers = {issue["number"] for issue in github_issues}
        
        for job in local_jobs:
            if job.issue_number not in github_issue_numbers:
                sync_results["orphaned_local_jobs"] += 1
                logger.warning(
                    "Found orphaned local job - no corresponding GitHub issue",
                    job_id=job.job_id,
                    issue=job.issue_number,
                    status=job.status
                )
                # Could implement cleanup logic here if needed

    async def _check_existing_worktree(self, issue_number: int) -> Optional[Dict[str, Any]]:
        """Check for existing worktree from previous interrupted job"""
        try:
            # Check job history for worktree information
            history = await self.job_manager.get_job_history(limit=50)
            
            for entry in history:
                if (entry.issue_number == issue_number and 
                    entry.status in ['running', 'pending'] and
                    entry.metadata):
                    
                    # Check if there's worktree info in metadata
                    worktree_info = entry.metadata.get('current_worktree_info') or entry.result.get('worktree_info') if entry.result else None
                    
                    if worktree_info and worktree_info.get('can_recover'):
                        # Verify the worktree still exists on disk
                        worktree_path = Path(worktree_info['worktree_path'])
                        if worktree_path.exists():
                            logger.info(
                                "Found recoverable worktree for issue",
                                issue=issue_number,
                                worktree_path=str(worktree_path),
                                branch=worktree_info.get('branch_name')
                            )
                            return worktree_info
                        else:
                            logger.warning(
                                "Worktree path no longer exists",
                                issue=issue_number,
                                worktree_path=str(worktree_path)
                            )
            
            return None
            
        except Exception as e:
            logger.error("Failed to check existing worktree", issue=issue_number, error=str(e))
            return None