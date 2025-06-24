"""
Configuration models for the modular agent framework
"""

from enum import Enum
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field, validator
from datetime import datetime
import uuid


class UserRole(str, Enum):
    """User roles with hierarchical permissions"""
    SUPER_ADMIN = "super_admin"
    ORG_ADMIN = "org_admin"
    MAINTAINER = "maintainer"
    CONTRIBUTOR = "contributor"
    USER = "user"


class Permission(str, Enum):
    """Granular permissions for different actions"""
    # Repository permissions
    TRIGGER_AGENT = "trigger_agent"
    CANCEL_JOBS = "cancel_jobs"
    VIEW_LOGS = "view_logs"
    RESTART_JOBS = "restart_jobs"
    
    # Configuration permissions
    MANAGE_AGENTS = "manage_agents"
    MANAGE_WORKFLOWS = "manage_workflows"
    MANAGE_TEMPLATES = "manage_templates"
    MANAGE_USERS = "manage_users"
    MANAGE_REPOSITORIES = "manage_repositories"
    
    # System permissions
    VIEW_METRICS = "view_metrics"
    MANAGE_SYSTEM = "manage_system"
    MANAGE_ORGANIZATION = "manage_organization"
    
    # Advanced permissions
    ESCALATE_ISSUES = "escalate_issues"
    OVERRIDE_VALIDATION = "override_validation"
    EMERGENCY_STOP = "emergency_stop"


class AgentPersonality(str, Enum):
    """Predefined agent personality types"""
    HELPFUL = "helpful"
    TECHNICAL = "technical"
    CONCISE = "concise"
    DETAILED = "detailed"
    EDUCATIONAL = "educational"
    PROFESSIONAL = "professional"
    CREATIVE = "creative"
    DEBUGGING = "debugging"
    CUSTOM = "custom"


class WorkflowStage(str, Enum):
    """Available workflow processing stages"""
    VALIDATION = "validation"
    PARSING = "parsing"
    ANALYSIS = "analysis"
    IMPLEMENTATION = "implementation"
    TESTING = "testing"
    REVIEW = "review"
    COMPLETION = "completion"


class TemplateType(str, Enum):
    """Template types for different use cases"""
    ISSUE_TEMPLATE = "issue_template"
    PROGRESS_UPDATE = "progress_update"
    COMPLETION = "completion"
    ERROR_RESPONSE = "error_response"
    FEEDBACK_REQUEST = "feedback_request"
    ESCALATION = "escalation"
    WELCOME = "welcome"
    HELP = "help"


# Base Models

class BaseConfigModel(BaseModel):
    """Base model for all configuration objects"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    updated_by: Optional[str] = None


# Organization Models

class Organization(BaseConfigModel):
    """Organization configuration"""
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, regex=r'^[a-z0-9-]+$')
    description: Optional[str] = None
    logo_url: Optional[str] = None
    website_url: Optional[str] = None
    settings: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class OrganizationCreate(BaseModel):
    """Model for creating organizations"""
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, regex=r'^[a-z0-9-]+$')
    description: Optional[str] = None
    logo_url: Optional[str] = None
    website_url: Optional[str] = None
    settings: Dict[str, Any] = Field(default_factory=dict)


# User Models

class User(BaseConfigModel):
    """User model with role and permission management"""
    github_username: str = Field(..., min_length=1, max_length=100)
    email: Optional[str] = Field(None, regex=r'^[^@]+@[^@]+\.[^@]+$')
    display_name: Optional[str] = Field(None, max_length=255)
    avatar_url: Optional[str] = None
    global_role: UserRole = UserRole.USER
    is_active: bool = True
    last_login: Optional[datetime] = None
    settings: Dict[str, Any] = Field(default_factory=dict)


class UserCreate(BaseModel):
    """Model for creating users"""
    github_username: str = Field(..., min_length=1, max_length=100)
    email: Optional[str] = Field(None, regex=r'^[^@]+@[^@]+\.[^@]+$')
    display_name: Optional[str] = Field(None, max_length=255)
    global_role: UserRole = UserRole.USER


class OrganizationMembership(BaseModel):
    """Organization membership with role and permissions"""
    organization_id: str
    user_id: str
    role: UserRole = UserRole.USER
    permissions: List[Permission] = Field(default_factory=list)
    joined_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = True


# Repository Models

class Repository(BaseConfigModel):
    """Repository configuration"""
    organization_id: str
    github_owner: str = Field(..., min_length=1, max_length=100)
    github_repo: str = Field(..., min_length=1, max_length=100)
    display_name: Optional[str] = None
    description: Optional[str] = None
    agent_config_id: Optional[str] = None
    workflow_config_id: Optional[str] = None
    is_active: bool = True
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None
    settings: Dict[str, Any] = Field(default_factory=dict)

    @property
    def full_name(self) -> str:
        """Get GitHub full name (owner/repo)"""
        return f"{self.github_owner}/{self.github_repo}"


class RepositoryCreate(BaseModel):
    """Model for creating repositories"""
    github_owner: str = Field(..., min_length=1, max_length=100)
    github_repo: str = Field(..., min_length=1, max_length=100)
    display_name: Optional[str] = None
    description: Optional[str] = None
    agent_config_id: Optional[str] = None
    workflow_config_id: Optional[str] = None
    webhook_url: Optional[str] = None
    settings: Dict[str, Any] = Field(default_factory=dict)


class RepositoryPermission(BaseModel):
    """Repository-specific permissions"""
    repository_id: str
    user_id: str
    role: UserRole = UserRole.USER
    permissions: List[Permission] = Field(default_factory=list)
    granted_at: datetime = Field(default_factory=datetime.utcnow)
    granted_by: Optional[str] = None
    is_active: bool = True


# Agent Configuration Models

class ResponseStyle(BaseModel):
    """Agent response style configuration"""
    tone: str = "professional"  # friendly, professional, casual, technical
    emoji_usage: str = "moderate"  # none, minimal, moderate, extensive
    explanation_depth: str = "balanced"  # minimal, balanced, detailed, comprehensive
    code_commenting: str = "standard"  # minimal, standard, extensive, educational
    format_preference: str = "mixed"  # lists, paragraphs, mixed, code_focused
    max_response_length: Optional[int] = None
    include_examples: bool = True
    include_alternatives: bool = False
    personalization_level: str = "standard"  # none, minimal, standard, high


class AgentCapability(str, Enum):
    """Available agent capabilities"""
    CODE_ANALYSIS = "code_analysis"
    CODE_GENERATION = "code_generation"
    DOCUMENTATION = "documentation"
    TESTING = "testing"
    DEBUGGING = "debugging"
    REFACTORING = "refactoring"
    SECURITY_REVIEW = "security_review"
    PERFORMANCE_OPTIMIZATION = "performance_optimization"
    ARCHITECTURE_REVIEW = "architecture_review"
    DEPLOYMENT_ASSISTANCE = "deployment_assistance"


class AgentConfig(BaseConfigModel):
    """Agent personality and behavior configuration"""
    organization_id: str
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    personality_type: AgentPersonality = AgentPersonality.HELPFUL
    system_prompt: str = Field(..., min_length=10)
    response_style: ResponseStyle = Field(default_factory=ResponseStyle)
    context_files: List[str] = Field(default_factory=list)
    capabilities: List[AgentCapability] = Field(default_factory=list)
    max_context_length: int = Field(default=8000, ge=1000, le=32000)
    timeout_seconds: int = Field(default=3600, ge=60, le=7200)
    is_default: bool = False
    is_active: bool = True
    settings: Dict[str, Any] = Field(default_factory=dict)

    @validator('system_prompt')
    def validate_system_prompt(cls, v):
        if len(v.strip()) < 10:
            raise ValueError('System prompt must be at least 10 characters')
        return v.strip()


class AgentConfigCreate(BaseModel):
    """Model for creating agent configurations"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    personality_type: AgentPersonality = AgentPersonality.HELPFUL
    system_prompt: str = Field(..., min_length=10)
    response_style: ResponseStyle = Field(default_factory=ResponseStyle)
    context_files: List[str] = Field(default_factory=list)
    capabilities: List[AgentCapability] = Field(default_factory=list)
    max_context_length: int = Field(default=8000, ge=1000, le=32000)
    timeout_seconds: int = Field(default=3600, ge=60, le=7200)
    settings: Dict[str, Any] = Field(default_factory=dict)


# Workflow Configuration Models

class ValidationRule(BaseModel):
    """Validation rule configuration"""
    name: str
    description: Optional[str] = None
    rule_type: str  # length, pattern, required, custom
    parameters: Dict[str, Any] = Field(default_factory=dict)
    error_message: str
    severity: str = "error"  # warning, error, critical
    is_active: bool = True


class ProcessingStep(BaseModel):
    """Workflow processing step configuration"""
    name: str
    stage: WorkflowStage
    description: Optional[str] = None
    processor_class: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    conditions: Dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: Optional[int] = None
    retry_count: int = 0
    is_optional: bool = False
    depends_on: List[str] = Field(default_factory=list)


class WorkflowConfig(BaseConfigModel):
    """Workflow processing configuration"""
    organization_id: str
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    task_types: List[str] = Field(default_factory=list)
    validation_rules: List[ValidationRule] = Field(default_factory=list)
    processing_steps: List[ProcessingStep] = Field(default_factory=list)
    state_config: Dict[str, Any] = Field(default_factory=dict)
    error_handling: Dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False
    is_active: bool = True
    settings: Dict[str, Any] = Field(default_factory=dict)


class WorkflowConfigCreate(BaseModel):
    """Model for creating workflow configurations"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    task_types: List[str] = Field(default_factory=list)
    validation_rules: List[ValidationRule] = Field(default_factory=list)
    processing_steps: List[ProcessingStep] = Field(default_factory=list)
    state_config: Dict[str, Any] = Field(default_factory=dict)
    error_handling: Dict[str, Any] = Field(default_factory=dict)
    settings: Dict[str, Any] = Field(default_factory=dict)


# Template Models

class TemplateVariable(BaseModel):
    """Template variable definition"""
    name: str
    type: str = "string"  # string, number, boolean, date, list, object
    description: Optional[str] = None
    default_value: Optional[Any] = None
    is_required: bool = False
    validation_pattern: Optional[str] = None


class Template(BaseConfigModel):
    """Template configuration for dynamic content"""
    organization_id: str
    name: str = Field(..., min_length=1, max_length=255)
    template_type: TemplateType
    description: Optional[str] = None
    content: str = Field(..., min_length=1)
    variables: List[TemplateVariable] = Field(default_factory=list)
    style_config: Dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False
    is_active: bool = True
    tags: List[str] = Field(default_factory=list)


class TemplateCreate(BaseModel):
    """Model for creating templates"""
    name: str = Field(..., min_length=1, max_length=255)
    template_type: TemplateType
    description: Optional[str] = None
    content: str = Field(..., min_length=1)
    variables: List[TemplateVariable] = Field(default_factory=list)
    style_config: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)


# Analytics and Monitoring Models

class ConfigurationMetrics(BaseModel):
    """Configuration performance metrics"""
    config_id: str
    config_type: str  # agent, workflow, template
    metric_type: str  # performance, usage, success_rate
    value: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SystemHealth(BaseModel):
    """System health status"""
    component: str
    status: str  # healthy, degraded, unhealthy
    message: Optional[str] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)
    last_check: datetime = Field(default_factory=datetime.utcnow)


# Response Models

class ConfigurationSummary(BaseModel):
    """Summary of configuration status"""
    organizations_count: int
    repositories_count: int
    users_count: int
    agent_configs_count: int
    workflow_configs_count: int
    templates_count: int
    system_health: List[SystemHealth]


class PermissionCheck(BaseModel):
    """Permission check result"""
    user_id: str
    repository_id: Optional[str] = None
    permission: Permission
    granted: bool
    reason: Optional[str] = None
    checked_at: datetime = Field(default_factory=datetime.utcnow)


# Update Models

class ConfigurationUpdate(BaseModel):
    """Base model for configuration updates"""
    updated_by: str
    update_reason: Optional[str] = None
    changes: Dict[str, Any] = Field(default_factory=dict)


class AgentConfigUpdate(ConfigurationUpdate):
    """Agent configuration update"""
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    response_style: Optional[ResponseStyle] = None
    capabilities: Optional[List[AgentCapability]] = None
    is_active: Optional[bool] = None
    settings: Optional[Dict[str, Any]] = None


class WorkflowConfigUpdate(ConfigurationUpdate):
    """Workflow configuration update"""
    name: Optional[str] = None
    description: Optional[str] = None
    validation_rules: Optional[List[ValidationRule]] = None
    processing_steps: Optional[List[ProcessingStep]] = None
    is_active: Optional[bool] = None
    settings: Optional[Dict[str, Any]] = None


# Role Hierarchy and Default Permissions

ROLE_HIERARCHY = {
    UserRole.SUPER_ADMIN: [
        Permission.MANAGE_SYSTEM,
        Permission.MANAGE_ORGANIZATION,
        Permission.MANAGE_USERS,
        Permission.MANAGE_AGENTS,
        Permission.MANAGE_WORKFLOWS,
        Permission.MANAGE_TEMPLATES,
        Permission.MANAGE_REPOSITORIES,
        Permission.VIEW_METRICS,
        Permission.TRIGGER_AGENT,
        Permission.CANCEL_JOBS,
        Permission.VIEW_LOGS,
        Permission.RESTART_JOBS,
        Permission.ESCALATE_ISSUES,
        Permission.OVERRIDE_VALIDATION,
        Permission.EMERGENCY_STOP,
    ],
    UserRole.ORG_ADMIN: [
        Permission.MANAGE_ORGANIZATION,
        Permission.MANAGE_USERS,
        Permission.MANAGE_AGENTS,
        Permission.MANAGE_WORKFLOWS,
        Permission.MANAGE_TEMPLATES,
        Permission.MANAGE_REPOSITORIES,
        Permission.VIEW_METRICS,
        Permission.TRIGGER_AGENT,
        Permission.CANCEL_JOBS,
        Permission.VIEW_LOGS,
        Permission.RESTART_JOBS,
        Permission.ESCALATE_ISSUES,
        Permission.OVERRIDE_VALIDATION,
    ],
    UserRole.MAINTAINER: [
        Permission.MANAGE_AGENTS,
        Permission.MANAGE_WORKFLOWS,
        Permission.MANAGE_TEMPLATES,
        Permission.VIEW_METRICS,
        Permission.TRIGGER_AGENT,
        Permission.CANCEL_JOBS,
        Permission.VIEW_LOGS,
        Permission.RESTART_JOBS,
        Permission.ESCALATE_ISSUES,
    ],
    UserRole.CONTRIBUTOR: [
        Permission.TRIGGER_AGENT,
        Permission.CANCEL_JOBS,
        Permission.VIEW_LOGS,
        Permission.RESTART_JOBS,
    ],
    UserRole.USER: [
        Permission.TRIGGER_AGENT,
        Permission.VIEW_LOGS,
    ],
}