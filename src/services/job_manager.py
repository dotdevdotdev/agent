"""
Job management service for handling long-running AI processing tasks
"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import structlog

from src.models.jobs import JobCreate, JobResponse, JobStatus, JobUpdate, JobHistoryEntry

logger = structlog.get_logger()


class JobManager:
    """
    Manages long-running jobs for AI processing with persistent history
    """

    def __init__(self, history_file: str = "job_history.json"):
        self._jobs: Dict[str, JobResponse] = {}
        self._job_logs: Dict[str, List[str]] = {}
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._history_file = Path(history_file)
        self._history: List[JobHistoryEntry] = []
        self._load_history()

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

        # Archive job to history if it's completed
        if status in ["completed", "failed", "cancelled"]:
            issue_title = job.metadata.get('parsed_task', {}).get('title', '') if job.metadata else ''
            await self._archive_job_to_history(job, issue_title)

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

        # Update progress (convert percentage to fraction)
        job.progress = float(progress) / 100.0
        
        # Add progress log
        await self.add_job_log(job_id, f"Progress: {progress}% - {message}")

        logger.info(
            "Job progress updated", 
            job_id=job_id, 
            progress=progress, 
            message=message
        )

        return True

    def _load_history(self) -> None:
        """Load job history from file"""
        try:
            if self._history_file.exists():
                with open(self._history_file, 'r') as f:
                    history_data = json.load(f)
                    self._history = [
                        JobHistoryEntry.model_validate(entry) 
                        for entry in history_data
                    ]
                logger.info(f"Loaded {len(self._history)} jobs from history")
            else:
                self._history = []
                logger.info("No existing job history found")
        except Exception as e:
            logger.error("Failed to load job history", error=str(e))
            self._history = []

    def _save_history(self) -> None:
        """Save job history to file"""
        try:
            # Keep only last 1000 entries to prevent file from growing too large
            history_to_save = self._history[-1000:] if len(self._history) > 1000 else self._history
            
            with open(self._history_file, 'w') as f:
                json.dump(
                    [entry.model_dump(mode='json') for entry in history_to_save], 
                    f, 
                    indent=2,
                    default=str  # Handle datetime serialization
                )
            logger.debug(f"Saved {len(history_to_save)} jobs to history")
        except Exception as e:
            logger.error("Failed to save job history", error=str(e))

    async def _archive_job_to_history(self, job: JobResponse, issue_title: str = "") -> None:
        """Archive completed job to persistent history"""
        try:
            # Check if job is already archived to prevent duplicates
            if any(entry.job_id == job.job_id for entry in self._history):
                logger.debug("Job already archived, skipping", job_id=job.job_id)
                return
            
            # Create history entry
            history_entry = JobHistoryEntry.from_job_response(job, issue_title)
            
            # Add to memory history
            self._history.append(history_entry)
            
            # Save to file
            self._save_history()
            
            logger.info("Job archived to history", job_id=job.job_id, status=job.status)
        except Exception as e:
            logger.error("Failed to archive job to history", job_id=job.job_id, error=str(e))

    async def get_job_history(
        self, 
        status: Optional[JobStatus] = None,
        limit: int = 100, 
        offset: int = 0
    ) -> List[JobHistoryEntry]:
        """Get job history with optional filtering"""
        filtered_history = self._history
        
        # Filter by status
        if status:
            filtered_history = [h for h in filtered_history if h.status == status]
        
        # Sort by creation time (newest first)
        filtered_history.sort(key=lambda x: x.created_at, reverse=True)
        
        # Apply pagination
        return filtered_history[offset:offset + limit]

    async def get_job_statistics(self) -> Dict[str, any]:
        """Get job statistics from history"""
        if not self._history:
            return {
                "total_jobs": 0,
                "status_counts": {},
                "average_duration": None,
                "success_rate": 0.0
            }
        
        status_counts = {}
        durations = []
        
        for entry in self._history:
            # Count statuses
            status_counts[entry.status.value] = status_counts.get(entry.status.value, 0) + 1
            
            # Collect durations
            if entry.duration_seconds:
                durations.append(entry.duration_seconds)
        
        # Calculate success rate
        completed_count = status_counts.get("completed", 0)
        total_finished = sum(status_counts.get(s, 0) for s in ["completed", "failed", "cancelled"])
        success_rate = (completed_count / total_finished * 100) if total_finished > 0 else 0.0
        
        # Calculate average duration
        avg_duration = sum(durations) / len(durations) if durations else None
        
        return {
            "total_jobs": len(self._history),
            "status_counts": status_counts,
            "average_duration_seconds": avg_duration,
            "success_rate_percentage": round(success_rate, 2)
        }
