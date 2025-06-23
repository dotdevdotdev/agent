"""
Health check endpoints
"""

from datetime import datetime
from typing import Dict, Any

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config.settings import settings

router = APIRouter()
logger = structlog.get_logger()


@router.get("")
async def health_check() -> JSONResponse:
    """
    Health check endpoint for monitoring
    """
    try:
        health_data = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "1.0.0",
            "service": "agentic-github-issue-response",
            "port": settings.PORT,
            "debug": settings.DEBUG,
        }

        # TODO: Add additional health checks:
        # - Git availability
        # - Claude CLI availability
        # - GitHub API connectivity
        # - Disk space for worktrees

        return JSONResponse(content=health_data, status_code=200)

    except Exception as e:
        logger.error("Health check failed", error=str(e))
        return JSONResponse(
            content={
                "status": "unhealthy",
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e),
            },
            status_code=503,
        )


@router.get("/ready")
async def readiness_check() -> JSONResponse:
    """
    Readiness check endpoint for deployment
    """
    try:
        # Check if all required services are available
        checks = {
            "git": check_git_availability(),
            "claude_cli": check_claude_cli_availability(),
            "github_token": bool(settings.GITHUB_TOKEN),
            "webhook_secret": bool(settings.GITHUB_WEBHOOK_SECRET),
        }

        all_ready = all(checks.values())

        return JSONResponse(
            content={
                "ready": all_ready,
                "checks": checks,
                "timestamp": datetime.utcnow().isoformat(),
            },
            status_code=200 if all_ready else 503,
        )

    except Exception as e:
        logger.error("Readiness check failed", error=str(e))
        return JSONResponse(
            content={
                "ready": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            },
            status_code=503,
        )


def check_git_availability() -> bool:
    """Check if git is available"""
    try:
        import subprocess

        result = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def check_claude_cli_availability() -> bool:
    """Check if claude CLI is available"""
    try:
        import subprocess

        result = subprocess.run(
            [settings.CLAUDE_CODE_PATH, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False
