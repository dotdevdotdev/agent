"""
Simple configuration API endpoints for file-based agent management
"""

from typing import Dict, List, Any
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
import structlog

from src.services.agent_config_service import AgentConfigService

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/config", tags=["configuration"])

# Initialize services
agent_config_service = AgentConfigService()


@router.get("/agents", response_model=Dict[str, str])
async def list_available_agents():
    """List all available agent configurations"""
    try:
        agents = await agent_config_service.list_available_agents()
        return agents
    except Exception as e:
        logger.error("Failed to list agents", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/agents/{agent_id}", response_model=Dict[str, Any])
async def get_agent_info(agent_id: str):
    """Get information about a specific agent"""
    try:
        agent_info = await agent_config_service.get_agent_info(agent_id)
        return agent_info
    except Exception as e:
        logger.error("Failed to get agent info", agent_id=agent_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/agents/default/info", response_model=Dict[str, Any])
async def get_default_agent_info():
    """Get information about the default agent"""
    try:
        agent_info = await agent_config_service.get_agent_info()
        return agent_info
    except Exception as e:
        logger.error("Failed to get default agent info", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/agents/reload")
async def reload_agent_configurations():
    """Reload all agent configurations from disk"""
    try:
        await agent_config_service.reload_agents()
        return JSONResponse(content={"success": True, "message": "Agent configurations reloaded"})
    except Exception as e:
        logger.error("Failed to reload agents", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/agents/validate")
async def validate_agent_config(config_data: Dict[str, Any]):
    """Validate agent configuration data"""
    try:
        validation_result = await agent_config_service.validate_agent_config(config_data)
        return validation_result
    except Exception as e:
        logger.error("Failed to validate agent config", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/health")
async def get_configuration_health():
    """Get configuration system health status"""
    try:
        # Simple health check for file-based system
        agents = await agent_config_service.list_available_agents()
        agent_count = len(agents)
        
        # Check if we have at least a default agent
        has_default = 'default' in agents or agent_count > 0
        
        return {
            "status": "healthy" if has_default else "warning",
            "agent_count": agent_count,
            "has_default_agent": has_default,
            "available_agents": list(agents.keys()) if agent_count <= 10 else f"{agent_count} agents available",
            "message": "File-based agent configuration system operational"
        }
    except Exception as e:
        logger.error("Failed to get health status", error=str(e))
        return {
            "status": "unhealthy",
            "error": str(e),
            "message": "Configuration system error"
        }