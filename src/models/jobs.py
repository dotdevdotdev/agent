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

    @classmethod
    def create_new(cls, job_create: JobCreate) -> "JobResponse":
        """Create a new job response from job creation request"""
        return cls(
            job_id=str(uuid.uuid4()),
            status=JobStatus.PENDING,
            issue_number=job_create.issue_number,
            repository_full_name=job_create.repository_full_name,
            created_at=datetime.utcnow(),
        )


class JobUpdate(BaseModel):
    """Job update model for status changes"""

    status: Optional[JobStatus] = None
    progress: Optional[float] = Field(None, ge=0.0, le=1.0)
    error_message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
