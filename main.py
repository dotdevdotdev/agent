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
from src.services.database_service import database_service
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
    # Initialize database service
    await database_service.initialize()
    
    logger.info(
        "Starting Agentic GitHub Issue Response System with Configuration Framework",
        host=settings.HOST,
        port=settings.PORT,
        database_initialized=True
    )


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up on shutdown"""
    # Close database connections
    await database_service.close()
    
    logger.info("Shutting down Agentic GitHub Issue Response System")


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
    )
