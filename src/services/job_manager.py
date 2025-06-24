"""
Job management service for handling long-running AI processing tasks
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional
import structlog

from src.models.jobs import JobCreate, JobResponse, JobStatus, JobUpdate

logger = structlog.get_logger()


class JobManager:
    """
    Manages long-running jobs for AI processing
    Note: This is an in-memory implementation for development.
    In production, consider using Redis, PostgreSQL, or a proper job queue.
    """

    def __init__(self):
        self._jobs: Dict[str, JobResponse] = {}
        self._job_logs: Dict[str, List[str]] = {}
        self._running_tasks: Dict[str, asyncio.Task] = {}

    async def create_job(self, job_create: JobCreate) -> JobResponse:
        """Create a new job"""
        job = JobResponse.create_new(job_create)
        self._jobs[job.job_id] = job
        self._job_logs[job.job_id] = []

        logger.info(
            "Job created",
            job_id=job.job_id,
            issue_number=job.issue_number,
            repository=job.repository_full_name,
        )

        return job

    async def get_job(self, job_id: str) -> Optional[JobResponse]:
        """Get a job by ID"""
        return self._jobs.get(job_id)

    async def list_jobs(
        self, status: Optional[JobStatus] = None, limit: int = 50, offset: int = 0
    ) -> List[JobResponse]:
        """List jobs with optional filtering"""
        jobs = list(self._jobs.values())

        # Filter by status if provided
        if status:
            jobs = [job for job in jobs if job.status == status]

        # Sort by creation time (newest first)
        jobs.sort(key=lambda x: x.created_at, reverse=True)

        # Apply pagination
        return jobs[offset : offset + limit]

    async def update_job_status(
        self,
        job_id: str,
        status: str,
        progress: Optional[float] = None,
        error_message: Optional[str] = None,
        result: Optional[Dict] = None,
    ) -> bool:
        """Update job status and metadata"""
        job = self._jobs.get(job_id)
        if not job:
            return False

        # Update status
        job.status = JobStatus(status)

        # Update timestamps
        if status == "running" and not job.started_at:
            job.started_at = datetime.utcnow()
        elif status in ["completed", "failed", "cancelled"]:
            job.completed_at = datetime.utcnow()

        # Update optional fields
        if progress is not None:
            job.progress = progress
        if error_message:
            job.error_message = error_message
        if result:
            job.result = result

        # Log the update
        await self.add_job_log(
            job_id,
            f"Status updated to {status}"
            + (f" - {error_message}" if error_message else ""),
        )

        logger.info(
            "Job status updated", job_id=job_id, status=status, progress=progress
        )

        return True

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a job"""
        job = self._jobs.get(job_id)
        if not job:
            return False

        # Can only cancel pending or running jobs
        if job.status not in [JobStatus.PENDING, JobStatus.RUNNING]:
            return False

        # Cancel running task if it exists
        if job_id in self._running_tasks:
            task = self._running_tasks[job_id]
            task.cancel()
            del self._running_tasks[job_id]

        # Update job status
        await self.update_job_status(job_id, "cancelled")

        return True

    async def add_job_log(self, job_id: str, message: str) -> None:
        """Add a log message to a job"""
        if job_id not in self._job_logs:
            self._job_logs[job_id] = []

        timestamp = datetime.utcnow().isoformat()
        log_entry = f"[{timestamp}] {message}"
        self._job_logs[job_id].append(log_entry)

        # Keep only last 1000 log entries per job
        if len(self._job_logs[job_id]) > 1000:
            self._job_logs[job_id] = self._job_logs[job_id][-1000:]

    async def get_job_logs(self, job_id: str) -> Optional[List[str]]:
        """Get logs for a job"""
        return self._job_logs.get(job_id)

    def get_active_job_count(self) -> int:
        """Get count of active (pending or running) jobs"""
        return len(
            [
                job
                for job in self._jobs.values()
                if job.status in [JobStatus.PENDING, JobStatus.RUNNING]
            ]
        )

    async def cleanup_completed_jobs(self, max_age_hours: int = 24) -> int:
        """
        Clean up completed jobs older than max_age_hours
        Returns number of jobs cleaned up
        """
        cutoff_time = datetime.utcnow().timestamp() - (max_age_hours * 3600)
        jobs_to_remove = []

        for job_id, job in self._jobs.items():
            if (
                job.status
                in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]
                and job.completed_at
                and job.completed_at.timestamp() < cutoff_time
            ):
                jobs_to_remove.append(job_id)

        # Remove old jobs and their logs
        for job_id in jobs_to_remove:
            del self._jobs[job_id]
            if job_id in self._job_logs:
                del self._job_logs[job_id]

        if jobs_to_remove:
            logger.info(f"Cleaned up {len(jobs_to_remove)} old jobs")

        return len(jobs_to_remove)

    async def update_job_progress(self, job_id: str, progress: int, message: str) -> bool:
        """Update job progress with message"""
        job = self._jobs.get(job_id)
        if not job:
            return False

        # Update progress
        job.progress = float(progress)
        
        # Add progress log
        await self.add_job_log(job_id, f"Progress: {progress}% - {message}")

        logger.info(
            "Job progress updated", 
            job_id=job_id, 
            progress=progress, 
            message=message
        )

        return True
