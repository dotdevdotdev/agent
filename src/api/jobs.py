"""
Job management endpoints
"""

from typing import List, Optional

import structlog
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from src.models.jobs import JobResponse, JobStatus
from src.services.job_manager import JobManager

router = APIRouter()
logger = structlog.get_logger()
job_manager = JobManager()


@router.get("/{job_id}", response_model=JobResponse)
async def get_job_status(job_id: str) -> JobResponse:
    """
    Get the status of a specific job
    """
    try:
        job = await job_manager.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        return job

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get job status", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("", response_model=List[JobResponse])
async def list_jobs(
    status: Optional[JobStatus] = Query(None, description="Filter by job status"),
    limit: int = Query(
        50, ge=1, le=100, description="Maximum number of jobs to return"
    ),
    offset: int = Query(0, ge=0, description="Number of jobs to skip"),
) -> List[JobResponse]:
    """
    List jobs with optional filtering
    """
    try:
        jobs = await job_manager.list_jobs(status=status, limit=limit, offset=offset)
        return jobs

    except Exception as e:
        logger.error("Failed to list jobs", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/{job_id}")
async def cancel_job(job_id: str) -> JSONResponse:
    """
    Cancel a running or pending job
    """
    try:
        success = await job_manager.cancel_job(job_id)
        if not success:
            raise HTTPException(
                status_code=404, detail="Job not found or cannot be cancelled"
            )

        logger.info("Job cancelled", job_id=job_id)
        return JSONResponse(
            content={"message": "Job cancelled successfully"}, status_code=200
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to cancel job", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{job_id}/logs")
async def get_job_logs(job_id: str) -> JSONResponse:
    """
    Get logs for a specific job
    """
    try:
        logs = await job_manager.get_job_logs(job_id)
        if logs is None:
            raise HTTPException(status_code=404, detail="Job not found")

        return JSONResponse(content={"logs": logs})

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get job logs", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")
