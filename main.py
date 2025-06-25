#!/usr/bin/env python3
"""
Agentic GitHub Issue Response System
Main application entry point
"""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog

from src.api.webhooks import router as webhook_router
from src.api.health import router as health_router
from src.api.jobs import router as jobs_router
from src.api.configuration import router as config_router
from config.settings import settings

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Create FastAPI application
app = FastAPI(
    title="Agentic GitHub Issue Response System",
    description="AI-powered system for automatically responding to GitHub issues",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.DEBUG else ["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health_router, prefix="/health", tags=["health"])
app.include_router(webhook_router, prefix="/webhook", tags=["webhooks"])
app.include_router(jobs_router, prefix="/jobs", tags=["jobs"])
app.include_router(config_router, tags=["configuration"])


@app.get("/", tags=["root"])
async def root():
    """Welcome endpoint for the Agentic GitHub Issue Response System"""
    return {
        "message": "🤖 Agentic GitHub Issue Response System",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health",
        "description": "AI-powered system for automatically responding to GitHub issues"
    }


@app.on_event("startup")
async def startup_event():
    """Initialize application on startup"""
    logger.info(
        "Starting Agentic GitHub Issue Response System with File-Based Configuration",
        host=settings.HOST,
        port=settings.PORT,
        config_system="file_based"
    )
    
    # Perform startup synchronization with GitHub
    try:
        from src.services.startup_sync import StartupSyncService
        from src.services.shared_services import get_github_client, get_job_manager, get_state_machine
        
        # Get shared service instances
        github_client = get_github_client()
        job_manager = get_job_manager()
        state_machine = get_state_machine()
        sync_service = StartupSyncService(github_client, job_manager, state_machine)
        
        # Run synchronization
        sync_results = await sync_service.sync_on_startup()
        
        logger.info(
            "Startup synchronization completed",
            github_issues=sync_results["github_issues_found"],
            jobs_recovered=sync_results["jobs_recovered"],
            jobs_restarted=sync_results["jobs_restarted"],
            orphaned_states=sync_results["orphaned_github_states"],
            errors=len(sync_results["errors"])
        )
        
        if sync_results["errors"]:
            logger.warning("Startup sync errors", errors=sync_results["errors"][:3])  # Log first 3 errors
            
    except Exception as e:
        logger.error("Startup synchronization failed", error=str(e))
        # Don't fail startup if sync fails - continue running


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up on shutdown"""
    logger.info("Shutting down Agentic GitHub Issue Response System")


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,  # Disabled to prevent worktree file changes from restarting server
        log_level=settings.LOG_LEVEL.lower(),
    )
