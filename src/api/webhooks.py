"""
Enhanced GitHub webhook endpoints with intelligent event routing
"""

import hashlib
import hmac
from typing import Dict, Any

import structlog
from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks
from fastapi.responses import JSONResponse

from config.settings import settings
from src.models.github import GitHubWebhookPayload
from src.services.shared_services import get_event_router
from src.utils.webhook_validator import validate_github_webhook

router = APIRouter()
logger = structlog.get_logger()


async def verify_webhook_signature(request: Request) -> None:
    """Verify GitHub webhook signature"""
    signature = request.headers.get("X-Hub-Signature-256")
    if not signature:
        # Log and reject requests without signature
        user_agent = request.headers.get("User-Agent", "unknown")
        logger.warning("Webhook without signature rejected", user_agent=user_agent)
        raise HTTPException(status_code=401, detail="Missing webhook signature")

    body = await request.body()
    if not body:
        logger.warning("Empty webhook body in signature verification")
        raise HTTPException(status_code=400, detail="Empty webhook body")
        
    if not validate_github_webhook(body, signature, settings.GITHUB_WEBHOOK_SECRET):
        logger.warning("Invalid webhook signature", signature=signature[:20] + "...")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


@router.post("/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_webhook_signature),
) -> JSONResponse:
    """
    Enhanced GitHub webhook handler with intelligent event routing
    """
    # Get event type and payload
    event_type = request.headers.get("X-GitHub-Event", "unknown")
    delivery_id = request.headers.get("X-GitHub-Delivery", "unknown")
    
    try:
        body = await request.body()
        logger.info("Webhook received", 
                   body_length=len(body),
                   user_agent=request.headers.get("User-Agent", "unknown"),
                   content_type=request.headers.get("Content-Type", "unknown"),
                   event_type=event_type)
        
        if not body:
            logger.error("Empty webhook body received", 
                        user_agent=request.headers.get("User-Agent"))
            raise HTTPException(status_code=400, detail="Empty payload")
        
        # Parse JSON from the body bytes
        import json
        payload = json.loads(body.decode('utf-8'))
    except Exception as e:
        logger.error("Failed to parse webhook payload", 
                    error=str(e),
                    user_agent=request.headers.get("User-Agent", "unknown"),
                    body_preview=str(body[:100]) if 'body' in locals() else "no_body")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    logger.info(
        "Received GitHub webhook",
        event_type=event_type,
        delivery_id=delivery_id,
        action=payload.get('action'),
        repository=payload.get('repository', {}).get('full_name'),
        issue_number=payload.get('issue', {}).get('number') or payload.get('number')
    )

    try:
        # Get shared event router
        event_router = get_event_router()
        
        # Clean up event cache periodically
        if delivery_id.endswith('0'):  # Every ~10th event
            await event_router.cleanup_event_cache()

        # Route to appropriate processor
        result = await event_router.route_event(event_type, payload)
        
        # Log result
        logger.info(
            "Webhook event processed",
            event_type=event_type,
            delivery_id=delivery_id,
            status=result.get('status'),
            job_id=result.get('job_id')
        )

        # Return appropriate response
        status_code = result.get('status_code', 200)
        if result.get('status') == 'error':
            status_code = 500
        elif result.get('status') in ['accepted', 'restarted']:
            status_code = 202

        return JSONResponse(content=result, status_code=status_code)

    except Exception as e:
        logger.error(
            "Webhook processing failed",
            event_type=event_type,
            delivery_id=delivery_id,
            error=str(e)
        )
        return JSONResponse(
            content={
                "status": "error", 
                "error": "Internal processing error",
                "event_type": event_type
            }, 
            status_code=500
        )


# Health check endpoint for webhook service
@router.get("/health")
async def webhook_health() -> JSONResponse:
    """Health check for webhook service"""
    try:
        event_router = get_event_router()
        stats = event_router.get_event_stats()
        return JSONResponse(content={
            "status": "healthy",
            "service": "webhook-handler",
            "event_router_stats": stats
        })
    except Exception as e:
        logger.error("Health check failed", error=str(e))
        return JSONResponse(
            content={"status": "unhealthy", "error": str(e)}, 
            status_code=500
        )
