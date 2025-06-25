"""
Job management data models
"""

from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
import uuid


class JobStatus(str, Enum):
    """Job status enumeration"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobCreate(BaseModel):
    """Job creation request"""

    issue_number: int
    repository_full_name: str
    issue_title: str
    issue_body: Optional[str] = None
    priority: int = Field(default=1, ge=1, le=10)
    metadata: Optional[Dict[str, Any]] = None


class JobResponse(BaseModel):
    """Job response model"""

    job_id: str
    status: JobStatus
    issue_number: int
    repository_full_name: str
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    metadata: Optional[Dict[str, Any]] = None

    @classmethod
    def create_new(cls, job_create: JobCreate) -> "JobResponse":
        """Create a new job response from job creation request"""
        return cls(
            job_id=str(uuid.uuid4()),
            status=JobStatus.PENDING,
            issue_number=job_create.issue_number,
            repository_full_name=job_create.repository_full_name,
            created_at=datetime.utcnow(),
            metadata=job_create.metadata,
        )


class JobUpdate(BaseModel):
    """Job update model for status changes"""

    status: Optional[JobStatus] = None
    progress: Optional[float] = Field(None, ge=0.0, le=1.0)
    error_message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class JobHistoryEntry(BaseModel):
    """Historical record of a job for persistence"""
    
    job_id: str
    status: JobStatus
    issue_number: int
    repository_full_name: str
    issue_title: str
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    metadata: Optional[Dict[str, Any]] = None
    duration_seconds: Optional[float] = None
    
    @classmethod
    def from_job_response(cls, job: JobResponse, issue_title: str = "") -> "JobHistoryEntry":
        """Create history entry from job response"""
        duration = None
        if job.started_at and job.completed_at:
            duration = (job.completed_at - job.started_at).total_seconds()
        elif job.started_at:
            duration = (datetime.utcnow() - job.started_at).total_seconds()
            
        return cls(
            job_id=job.job_id,
            status=job.status,
            issue_number=job.issue_number,
            repository_full_name=job.repository_full_name,
            issue_title=issue_title,
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            error_message=job.error_message,
            result=job.result,
            progress=job.progress,
            metadata=job.metadata,
            duration_seconds=duration
        )
