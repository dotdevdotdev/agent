"""
Configuration management API endpoints
Provides REST API for managing organizations, users, repositories, agents, and workflows
"""

from typing import Dict, List, Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import structlog

from src.models.configuration import *
from src.services.database_service import DatabaseService, database_service
from src.services.permission_manager import PermissionManager
from src.services.agent_config_service import AgentConfigService
from src.services.workflow_engine import WorkflowEngine

logger = structlog.get_logger()
security = HTTPBearer(auto_error=False)

# Initialize services
permission_manager = PermissionManager(database_service)
agent_config_service = AgentConfigService(database_service)
workflow_engine = WorkflowEngine(database_service)

router = APIRouter(prefix="/api/v1/config", tags=["configuration"])


# Authentication and authorization
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> User:
    """Get current authenticated user"""
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # In a real implementation, this would validate the JWT token
    # For now, we'll use a simplified approach
    token = credentials.credentials
    
    # Extract user from token (simplified)
    # This should use proper JWT validation
    user_id = "test-user-id"  # Placeholder
    
    user = await database_service.get_user(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid user")
    
    return user


async def check_permission(permission: Permission, user: User = Depends(get_current_user),
                         repository_id: Optional[str] = None,
                         organization_id: Optional[str] = None) -> User:
    """Check if user has required permission"""
    permission_check = await permission_manager.check_permission(
        user.id, permission, repository_id, organization_id
    )
    
    if not permission_check.granted:
        raise HTTPException(
            status_code=403,
            detail=f"Permission denied: {permission.value} - {permission_check.reason}"
        )
    
    return user


# Organization endpoints
@router.post("/organizations", response_model=Organization)
async def create_organization(
    org: OrganizationCreate,
    user: User = Depends(lambda: check_permission(Permission.MANAGE_ORGANIZATION))
):
    """Create new organization"""
    try:
        # Check if slug already exists
        existing = await database_service.get_organization_by_slug(org.slug)
        if existing:
            raise HTTPException(status_code=409, detail="Organization slug already exists")
        
        organization = await database_service.create_organization(org, user.github_username)
        
        # Add creator as organization admin
        await permission_manager.add_user_to_organization(
            user.id, organization.id, UserRole.ORG_ADMIN, user.github_username
        )
        
        logger.info("Organization created via API", org_id=organization.id, created_by=user.github_username)
        return organization
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create organization", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/organizations", response_model=List[Organization])
async def list_organizations(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user)
):
    """List organizations user has access to"""
    try:
        # For super admins, return all organizations
        if user.global_role == UserRole.SUPER_ADMIN:
            return await database_service.list_organizations(limit, offset)
        
        # For others, return only organizations they're members of
        # This would need to be implemented in the database service
        return await database_service.list_organizations(limit, offset)
        
    except Exception as e:
        logger.error("Failed to list organizations", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/organizations/{org_id}", response_model=Organization)
async def get_organization(
    org_id: str = Path(...),
    user: User = Depends(get_current_user)
):
    """Get organization by ID"""
    try:
        organization = await database_service.get_organization(org_id)
        if not organization:
            raise HTTPException(status_code=404, detail="Organization not found")
        
        # Check if user has access to this organization
        permission_check = await permission_manager.check_permission(
            user.id, Permission.VIEW_METRICS, organization_id=org_id
        )
        
        if not permission_check.granted and user.global_role not in [UserRole.SUPER_ADMIN, UserRole.ORG_ADMIN]:
            raise HTTPException(status_code=403, detail="Access denied")
        
        return organization
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get organization", org_id=org_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


# Repository endpoints
@router.post("/organizations/{org_id}/repositories", response_model=Repository)
async def create_repository(
    org_id: str = Path(...),
    repo: RepositoryCreate = Body(...),
    user: User = Depends(lambda: check_permission(Permission.MANAGE_REPOSITORIES))
):
    """Create new repository"""
    try:
        # Verify organization exists
        organization = await database_service.get_organization(org_id)
        if not organization:
            raise HTTPException(status_code=404, detail="Organization not found")
        
        # Check if repository already exists
        existing = await database_service.get_repository_by_name(repo.github_owner, repo.github_repo)
        if existing:
            raise HTTPException(status_code=409, detail="Repository already registered")
        
        repository = await database_service.create_repository(repo, org_id, user.github_username)
        
        logger.info("Repository created via API", repo_id=repository.id, created_by=user.github_username)
        return repository
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create repository", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/organizations/{org_id}/repositories", response_model=List[Repository])
async def list_repositories(
    org_id: str = Path(...),
    user: User = Depends(get_current_user)
):
    """List repositories in organization"""
    try:
        # Check organization access
        organization = await database_service.get_organization(org_id)
        if not organization:
            raise HTTPException(status_code=404, detail="Organization not found")
        
        repositories = await permission_manager.get_user_repositories(user.id, org_id)
        return repositories
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to list repositories", org_id=org_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


# Agent configuration endpoints
@router.post("/organizations/{org_id}/agent-configs", response_model=AgentConfig)
async def create_agent_config(
    org_id: str = Path(...),
    config: AgentConfigCreate = Body(...),
    user: User = Depends(lambda: check_permission(Permission.MANAGE_AGENTS))
):
    """Create new agent configuration"""
    try:
        # Verify organization exists
        organization = await database_service.get_organization(org_id)
        if not organization:
            raise HTTPException(status_code=404, detail="Organization not found")
        
        agent_config = await agent_config_service.create_agent_config(
            org_id, config, user.github_username
        )
        
        logger.info("Agent config created via API", config_id=agent_config.id, created_by=user.github_username)
        return agent_config
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create agent config", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/organizations/{org_id}/agent-configs", response_model=List[AgentConfig])
async def list_agent_configs(
    org_id: str = Path(...),
    include_presets: bool = Query(False),
    user: User = Depends(get_current_user)
):
    """List agent configurations for organization"""
    try:
        # Check organization access
        permission_check = await permission_manager.check_permission(
            user.id, Permission.VIEW_METRICS, organization_id=org_id
        )
        
        if not permission_check.granted:
            raise HTTPException(status_code=403, detail="Access denied")
        
        configs = await agent_config_service.list_agent_configs(org_id, include_presets)
        return configs
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to list agent configs", org_id=org_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/organizations/{org_id}/agent-configs/{config_id}", response_model=AgentConfig)
async def get_agent_config(
    org_id: str = Path(...),
    config_id: str = Path(...),
    user: User = Depends(get_current_user)
):
    """Get agent configuration by ID"""
    try:
        # Check if it's a preset
        if config_id.startswith("preset_"):
            personality = AgentPersonality(config_id.replace("preset_", ""))
            preset = await agent_config_service.get_preset_config(personality)
            preset.organization_id = org_id
            return preset
        
        agent_config = await agent_config_service.get_agent_config(config_id)
        if not agent_config or agent_config.organization_id != org_id:
            raise HTTPException(status_code=404, detail="Agent configuration not found")
        
        return agent_config
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get agent config", config_id=config_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/organizations/{org_id}/agent-configs/{config_id}", response_model=AgentConfig)
async def update_agent_config(
    org_id: str = Path(...),
    config_id: str = Path(...),
    updates: AgentConfigUpdate = Body(...),
    user: User = Depends(lambda: check_permission(Permission.MANAGE_AGENTS))
):
    """Update agent configuration"""
    try:
        # Check if config exists and belongs to organization
        existing_config = await agent_config_service.get_agent_config(config_id)
        if not existing_config or existing_config.organization_id != org_id:
            raise HTTPException(status_code=404, detail="Agent configuration not found")
        
        updated_config = await agent_config_service.update_agent_config(
            config_id, updates, user.github_username
        )
        
        if not updated_config:
            raise HTTPException(status_code=404, detail="Agent configuration not found")
        
        logger.info("Agent config updated via API", config_id=config_id, updated_by=user.github_username)
        return updated_config
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update agent config", config_id=config_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


# Workflow configuration endpoints
@router.post("/organizations/{org_id}/workflows", response_model=WorkflowConfig)
async def create_workflow_config(
    org_id: str = Path(...),
    workflow: WorkflowConfigCreate = Body(...),
    user: User = Depends(lambda: check_permission(Permission.MANAGE_WORKFLOWS))
):
    """Create new workflow configuration"""
    try:
        # Verify organization exists
        organization = await database_service.get_organization(org_id)
        if not organization:
            raise HTTPException(status_code=404, detail="Organization not found")
        
        workflow_config = await workflow_engine.create_workflow_config(
            org_id, workflow, user.github_username
        )
        
        logger.info("Workflow config created via API", config_id=workflow_config.id, created_by=user.github_username)
        return workflow_config
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create workflow config", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/organizations/{org_id}/workflows", response_model=List[WorkflowConfig])
async def list_workflow_configs(
    org_id: str = Path(...),
    user: User = Depends(get_current_user)
):
    """List workflow configurations for organization"""
    try:
        # Check organization access
        permission_check = await permission_manager.check_permission(
            user.id, Permission.VIEW_METRICS, organization_id=org_id
        )
        
        if not permission_check.granted:
            raise HTTPException(status_code=403, detail="Access denied")
        
        configs = await workflow_engine.list_workflow_configs(org_id)
        return configs
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to list workflow configs", org_id=org_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/organizations/{org_id}/workflows/{workflow_id}", response_model=WorkflowConfig)
async def get_workflow_config(
    org_id: str = Path(...),
    workflow_id: str = Path(...),
    user: User = Depends(get_current_user)
):
    """Get workflow configuration by ID"""
    try:
        workflow_config = await workflow_engine.get_workflow_config(workflow_id)
        if not workflow_config or (workflow_config.organization_id and workflow_config.organization_id != org_id):
            raise HTTPException(status_code=404, detail="Workflow configuration not found")
        
        return workflow_config
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get workflow config", workflow_id=workflow_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


# User management endpoints
@router.post("/organizations/{org_id}/users/{user_id}/permissions")
async def grant_permission(
    org_id: str = Path(...),
    user_id: str = Path(...),
    permission_data: Dict[str, Any] = Body(...),
    current_user: User = Depends(lambda: check_permission(Permission.MANAGE_USERS))
):
    """Grant permission to user"""
    try:
        permission = Permission(permission_data["permission"])
        repository_id = permission_data.get("repository_id")
        
        success = await permission_manager.grant_permission(
            user_id, permission, repository_id, org_id, current_user.github_username
        )
        
        if not success:
            raise HTTPException(status_code=400, detail="Failed to grant permission")
        
        logger.info("Permission granted via API", user_id=user_id, permission=permission, granted_by=current_user.github_username)
        return JSONResponse(content={"success": True, "message": "Permission granted"})
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to grant permission", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/organizations/{org_id}/users/{user_id}/permissions")
async def revoke_permission(
    org_id: str = Path(...),
    user_id: str = Path(...),
    permission_data: Dict[str, Any] = Body(...),
    current_user: User = Depends(lambda: check_permission(Permission.MANAGE_USERS))
):
    """Revoke permission from user"""
    try:
        permission = Permission(permission_data["permission"])
        repository_id = permission_data.get("repository_id")
        
        success = await permission_manager.revoke_permission(
            user_id, permission, repository_id, org_id, current_user.github_username
        )
        
        if not success:
            raise HTTPException(status_code=400, detail="Failed to revoke permission")
        
        logger.info("Permission revoked via API", user_id=user_id, permission=permission, revoked_by=current_user.github_username)
        return JSONResponse(content={"success": True, "message": "Permission revoked"})
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to revoke permission", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/organizations/{org_id}/users/{user_id}/permissions", response_model=List[Permission])
async def get_user_permissions(
    org_id: str = Path(...),
    user_id: str = Path(...),
    repository_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user)
):
    """Get user permissions"""
    try:
        # Users can view their own permissions, or admins can view any
        if current_user.id != user_id:
            permission_check = await permission_manager.check_permission(
                current_user.id, Permission.MANAGE_USERS, organization_id=org_id
            )
            if not permission_check.granted:
                raise HTTPException(status_code=403, detail="Access denied")
        
        permissions = await permission_manager.get_user_permissions(user_id, repository_id, org_id)
        return permissions
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get user permissions", user_id=user_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


# Health and status endpoints
@router.get("/health", response_model=Dict[str, Any])
async def get_configuration_health():
    """Get configuration system health status"""
    try:
        health_status = await database_service.get_health_status()
        
        return {
            "status": "healthy" if all(h.status == "healthy" for h in health_status) else "degraded",
            "components": {
                h.component: {
                    "status": h.status,
                    "message": h.message,
                    "metrics": h.metrics,
                    "last_check": h.last_check.isoformat()
                }
                for h in health_status
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error("Failed to get health status", error=str(e))
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


@router.get("/summary", response_model=ConfigurationSummary)
async def get_configuration_summary(
    user: User = Depends(get_current_user)
):
    """Get configuration system summary"""
    try:
        # This would need to be implemented in the database service
        # For now, return placeholder data
        health_status = await database_service.get_health_status()
        
        return ConfigurationSummary(
            organizations_count=0,
            repositories_count=0,
            users_count=0,
            agent_configs_count=0,
            workflow_configs_count=0,
            templates_count=0,
            system_health=health_status
        )
        
    except Exception as e:
        logger.error("Failed to get configuration summary", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


# Personality presets endpoint
@router.get("/agent-presets", response_model=Dict[str, AgentConfig])
async def get_agent_presets():
    """Get all available agent personality presets"""
    try:
        presets = {}
        for personality in AgentPersonality:
            if personality != AgentPersonality.CUSTOM:
                preset = await agent_config_service.get_preset_config(personality)
                presets[personality.value] = preset
        
        return presets
        
    except Exception as e:
        logger.error("Failed to get agent presets", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


# Agent performance metrics
@router.get("/organizations/{org_id}/agent-configs/{config_id}/metrics")
async def get_agent_performance_metrics(
    org_id: str = Path(...),
    config_id: str = Path(...),
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user)
):
    """Get performance metrics for agent configuration"""
    try:
        # Check access to organization
        permission_check = await permission_manager.check_permission(
            user.id, Permission.VIEW_METRICS, organization_id=org_id
        )
        
        if not permission_check.granted:
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Check if config exists and belongs to organization
        if not config_id.startswith("preset_"):
            agent_config = await agent_config_service.get_agent_config(config_id)
            if not agent_config or agent_config.organization_id != org_id:
                raise HTTPException(status_code=404, detail="Agent configuration not found")
        
        metrics = await agent_config_service.get_performance_metrics(config_id, days)
        return metrics
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get agent metrics", config_id=config_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")