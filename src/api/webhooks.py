"""
GitHub webhook endpoints
"""

import hashlib
import hmac
from typing import Dict, Any

import structlog
from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks
from fastapi.responses import JSONResponse

from config.settings import settings
from src.models.github import GitHubWebhookPayload
from src.models.jobs import JobCreate, JobResponse
from src.services.job_manager import JobManager
from src.utils.webhook_validator import validate_github_webhook

router = APIRouter()
logger = structlog.get_logger()
job_manager = JobManager()


async def verify_webhook_signature(request: Request) -> None:
    """Verify GitHub webhook signature"""
    signature = request.headers.get("X-Hub-Signature-256")
    if not signature:
        raise HTTPException(status_code=401, detail="Missing webhook signature")

    body = await request.body()
    if not validate_github_webhook(body, signature, settings.GITHUB_WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


@router.post("/github")
async def github_webhook(
    payload: GitHubWebhookPayload,
    background_tasks: BackgroundTasks,
    request: Request,
    _: None = Depends(verify_webhook_signature),
) -> JSONResponse:
    """
    Handle GitHub webhook events for issues
    """
    logger.info(
        "Received GitHub webhook",
        action=payload.action,
        issue_number=payload.issue.number,
        repository=payload.repository.full_name,
    )

    # Only process 'opened' issue events for now
    if payload.action != "opened":
        logger.info("Ignoring non-opened issue event", action=payload.action)
        return JSONResponse(
            content={"message": f"Ignored {payload.action} event"}, status_code=200
        )

    try:
        # Create job for processing the issue
        job_create = JobCreate(
            issue_number=payload.issue.number,
            repository_full_name=payload.repository.full_name,
            issue_title=payload.issue.title,
            issue_body=payload.issue.body,
        )

        # Submit job to background processing
        job = await job_manager.create_job(job_create)

        # Add background task to process the issue
        background_tasks.add_task(process_github_issue, job.job_id, payload)

        logger.info(
            "Created job for GitHub issue",
            job_id=job.job_id,
            issue_number=payload.issue.number,
        )

        return JSONResponse(
            content={
                "message": "Issue processing job created",
                "job_id": job.job_id,
                "issue_number": payload.issue.number,
            },
            status_code=202,
        )

    except Exception as e:
        logger.error(
            "Failed to create job for GitHub issue",
            error=str(e),
            issue_number=payload.issue.number,
        )
        raise HTTPException(status_code=500, detail="Failed to create processing job")


async def process_github_issue(job_id: str, payload: GitHubWebhookPayload) -> None:
    """
    Background task to process GitHub issue with AI
    """
    try:
        logger.info("Starting issue processing", job_id=job_id)

        # Mark job as running
        await job_manager.update_job_status(job_id, "running")

        # TODO: Implement the actual processing logic:
        # 1. Create git worktree
        # 2. Run claude code CLI
        # 3. Process results
        # 4. Update GitHub issue
        # 5. Cleanup worktree

        # For now, just simulate processing
        import asyncio

        await asyncio.sleep(5)  # Simulate work

        # Mark job as completed
        await job_manager.update_job_status(
            job_id, "completed", result={"message": "Issue processed successfully"}
        )

        logger.info("Issue processing completed", job_id=job_id)

    except Exception as e:
        logger.error("Issue processing failed", job_id=job_id, error=str(e))
        await job_manager.update_job_status(job_id, "failed", error_message=str(e))
