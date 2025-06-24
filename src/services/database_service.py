"""
Database service for configuration framework
Handles all database operations for the modular agent system
"""

import asyncio
import json
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
import asyncpg
import structlog
from contextlib import asynccontextmanager

from src.models.configuration import *
from config.settings import settings

logger = structlog.get_logger()


class DatabaseService:
    """Database service for configuration management"""

    def __init__(self, connection_string: Optional[str] = None):
        self.connection_string = connection_string or self._get_connection_string()
        self.pool: Optional[asyncpg.Pool] = None
        self._initialized = False

    def _get_connection_string(self) -> str:
        """Build connection string from settings"""
        # For now, use SQLite for development, PostgreSQL for production
        db_url = getattr(settings, 'DATABASE_URL', None)
        if db_url:
            return db_url
        
        # Default to in-memory SQLite for development
        return "sqlite:///:memory:"

    async def initialize(self) -> None:
        """Initialize database connection and create tables"""
        if self._initialized:
            return

        try:
            # For PostgreSQL
            if self.connection_string.startswith('postgresql'):
                self.pool = await asyncpg.create_pool(
                    self.connection_string,
                    min_size=5,
                    max_size=20,
                    command_timeout=60
                )
            else:
                # For development, use in-memory dict storage
                self._memory_storage = {
                    'organizations': {},
                    'users': {},
                    'repositories': {},
                    'agent_configs': {},
                    'workflow_configs': {},
                    'templates': {},
                    'organization_memberships': {},
                    'repository_permissions': {},
                    'metrics': []
                }

            await self._create_tables()
            self._initialized = True
            logger.info("Database service initialized")

        except Exception as e:
            logger.error("Failed to initialize database", error=str(e))
            raise

    async def close(self) -> None:
        """Close database connections"""
        if self.pool:
            await self.pool.close()
        self._initialized = False
        logger.info("Database service closed")

    @asynccontextmanager
    async def get_connection(self):
        """Get database connection from pool"""
        if self.pool:
            async with self.pool.acquire() as connection:
                yield connection
        else:
            # For in-memory development mode
            yield self._memory_storage

    async def _create_tables(self) -> None:
        """Create database tables if they don't exist"""
        if self.pool:
            await self._create_postgresql_tables()
        else:
            # Tables already exist in memory dict
            pass

    async def _create_postgresql_tables(self) -> None:
        """Create PostgreSQL tables"""
        sql_commands = [
            """
            CREATE TABLE IF NOT EXISTS organizations (
                id UUID PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                slug VARCHAR(100) UNIQUE NOT NULL,
                description TEXT,
                logo_url TEXT,
                website_url TEXT,
                settings JSONB DEFAULT '{}',
                is_active BOOLEAN DEFAULT true,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                created_by VARCHAR(100),
                updated_by VARCHAR(100)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY,
                github_username VARCHAR(100) UNIQUE NOT NULL,
                email VARCHAR(255),
                display_name VARCHAR(255),
                avatar_url TEXT,
                global_role VARCHAR(50) DEFAULT 'user',
                is_active BOOLEAN DEFAULT true,
                last_login TIMESTAMP,
                settings JSONB DEFAULT '{}',
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                created_by VARCHAR(100),
                updated_by VARCHAR(100)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS organization_memberships (
                organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
                user_id UUID REFERENCES users(id) ON DELETE CASCADE,
                role VARCHAR(50) NOT NULL DEFAULT 'user',
                permissions TEXT[] DEFAULT '{}',
                joined_at TIMESTAMP DEFAULT NOW(),
                is_active BOOLEAN DEFAULT true,
                PRIMARY KEY (organization_id, user_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS repositories (
                id UUID PRIMARY KEY,
                organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
                github_owner VARCHAR(100) NOT NULL,
                github_repo VARCHAR(100) NOT NULL,
                display_name VARCHAR(255),
                description TEXT,
                agent_config_id UUID,
                workflow_config_id UUID,
                is_active BOOLEAN DEFAULT true,
                webhook_url TEXT,
                webhook_secret TEXT,
                settings JSONB DEFAULT '{}',
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                created_by VARCHAR(100),
                updated_by VARCHAR(100),
                UNIQUE(github_owner, github_repo)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS repository_permissions (
                repository_id UUID REFERENCES repositories(id) ON DELETE CASCADE,
                user_id UUID REFERENCES users(id) ON DELETE CASCADE,
                role VARCHAR(50) NOT NULL DEFAULT 'user',
                permissions TEXT[] DEFAULT '{}',
                granted_at TIMESTAMP DEFAULT NOW(),
                granted_by VARCHAR(100),
                is_active BOOLEAN DEFAULT true,
                PRIMARY KEY (repository_id, user_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS agent_configs (
                id UUID PRIMARY KEY,
                organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                personality_type VARCHAR(100) NOT NULL,
                system_prompt TEXT NOT NULL,
                response_style JSONB DEFAULT '{}',
                context_files TEXT[] DEFAULT '{}',
                capabilities TEXT[] DEFAULT '{}',
                max_context_length INTEGER DEFAULT 8000,
                timeout_seconds INTEGER DEFAULT 3600,
                is_default BOOLEAN DEFAULT false,
                is_active BOOLEAN DEFAULT true,
                settings JSONB DEFAULT '{}',
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                created_by VARCHAR(100),
                updated_by VARCHAR(100)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS workflow_configs (
                id UUID PRIMARY KEY,
                organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                task_types TEXT[] DEFAULT '{}',
                validation_rules JSONB DEFAULT '{}',
                processing_steps JSONB DEFAULT '{}',
                state_config JSONB DEFAULT '{}',
                error_handling JSONB DEFAULT '{}',
                is_default BOOLEAN DEFAULT false,
                is_active BOOLEAN DEFAULT true,
                settings JSONB DEFAULT '{}',
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                created_by VARCHAR(100),
                updated_by VARCHAR(100)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS templates (
                id UUID PRIMARY KEY,
                organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
                name VARCHAR(255) NOT NULL,
                template_type VARCHAR(100) NOT NULL,
                description TEXT,
                content TEXT NOT NULL,
                variables JSONB DEFAULT '{}',
                style_config JSONB DEFAULT '{}',
                is_default BOOLEAN DEFAULT false,
                is_active BOOLEAN DEFAULT true,
                tags TEXT[] DEFAULT '{}',
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                created_by VARCHAR(100),
                updated_by VARCHAR(100)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS configuration_metrics (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                config_id UUID NOT NULL,
                config_type VARCHAR(50) NOT NULL,
                metric_type VARCHAR(100) NOT NULL,
                value FLOAT NOT NULL,
                timestamp TIMESTAMP DEFAULT NOW(),
                metadata JSONB DEFAULT '{}'
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_org_memberships_user ON organization_memberships(user_id);
            CREATE INDEX IF NOT EXISTS idx_repo_permissions_user ON repository_permissions(user_id);
            CREATE INDEX IF NOT EXISTS idx_repositories_org ON repositories(organization_id);
            CREATE INDEX IF NOT EXISTS idx_agent_configs_org ON agent_configs(organization_id);
            CREATE INDEX IF NOT EXISTS idx_workflow_configs_org ON workflow_configs(organization_id);
            CREATE INDEX IF NOT EXISTS idx_templates_org ON templates(organization_id);
            CREATE INDEX IF NOT EXISTS idx_metrics_config ON configuration_metrics(config_id, timestamp);
            """
        ]

        async with self.get_connection() as conn:
            for sql in sql_commands:
                await conn.execute(sql)

    # Organization operations

    async def create_organization(self, org: OrganizationCreate, created_by: str) -> Organization:
        """Create new organization"""
        organization = Organization(
            **org.dict(),
            created_by=created_by,
            updated_by=created_by
        )

        if self.pool:
            async with self.get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO organizations (id, name, slug, description, logo_url, 
                                             website_url, settings, created_by, updated_by)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    organization.id, organization.name, organization.slug,
                    organization.description, organization.logo_url, organization.website_url,
                    json.dumps(organization.settings), organization.created_by,
                    organization.updated_by
                )
        else:
            self._memory_storage['organizations'][organization.id] = organization.dict()

        logger.info("Organization created", org_id=organization.id, name=organization.name)
        return organization

    async def get_organization(self, org_id: str) -> Optional[Organization]:
        """Get organization by ID"""
        if self.pool:
            async with self.get_connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM organizations WHERE id = $1 AND is_active = true",
                    org_id
                )
                if row:
                    return Organization(**dict(row))
        else:
            org_data = self._memory_storage['organizations'].get(org_id)
            if org_data:
                return Organization(**org_data)
        return None

    async def get_organization_by_slug(self, slug: str) -> Optional[Organization]:
        """Get organization by slug"""
        if self.pool:
            async with self.get_connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM organizations WHERE slug = $1 AND is_active = true",
                    slug
                )
                if row:
                    return Organization(**dict(row))
        else:
            for org_data in self._memory_storage['organizations'].values():
                if org_data['slug'] == slug and org_data.get('is_active', True):
                    return Organization(**org_data)
        return None

    async def list_organizations(self, limit: int = 50, offset: int = 0) -> List[Organization]:
        """List all organizations"""
        organizations = []
        
        if self.pool:
            async with self.get_connection() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM organizations WHERE is_active = true 
                    ORDER BY created_at DESC LIMIT $1 OFFSET $2
                    """,
                    limit, offset
                )
                organizations = [Organization(**dict(row)) for row in rows]
        else:
            all_orgs = [
                Organization(**org_data) 
                for org_data in self._memory_storage['organizations'].values()
                if org_data.get('is_active', True)
            ]
            organizations = sorted(all_orgs, key=lambda x: x.created_at, reverse=True)[offset:offset+limit]

        return organizations

    # User operations

    async def create_user(self, user: UserCreate, created_by: str) -> User:
        """Create new user"""
        user_obj = User(
            **user.dict(),
            created_by=created_by,
            updated_by=created_by
        )

        if self.pool:
            async with self.get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO users (id, github_username, email, display_name, 
                                     global_role, settings, created_by, updated_by)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    user_obj.id, user_obj.github_username, user_obj.email,
                    user_obj.display_name, user_obj.global_role.value,
                    json.dumps(user_obj.settings), user_obj.created_by, user_obj.updated_by
                )
        else:
            self._memory_storage['users'][user_obj.id] = user_obj.dict()

        logger.info("User created", user_id=user_obj.id, username=user_obj.github_username)
        return user_obj

    async def get_user(self, user_id: str) -> Optional[User]:
        """Get user by ID"""
        if self.pool:
            async with self.get_connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM users WHERE id = $1 AND is_active = true",
                    user_id
                )
                if row:
                    return User(**dict(row))
        else:
            user_data = self._memory_storage['users'].get(user_id)
            if user_data:
                return User(**user_data)
        return None

    async def get_user_by_github_username(self, username: str) -> Optional[User]:
        """Get user by GitHub username"""
        if self.pool:
            async with self.get_connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM users WHERE github_username = $1 AND is_active = true",
                    username
                )
                if row:
                    return User(**dict(row))
        else:
            for user_data in self._memory_storage['users'].values():
                if (user_data['github_username'] == username and 
                    user_data.get('is_active', True)):
                    return User(**user_data)
        return None

    # Repository operations

    async def create_repository(self, repo: RepositoryCreate, org_id: str, 
                              created_by: str) -> Repository:
        """Create new repository"""
        repository = Repository(
            **repo.dict(),
            organization_id=org_id,
            created_by=created_by,
            updated_by=created_by
        )

        if self.pool:
            async with self.get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO repositories (id, organization_id, github_owner, github_repo,
                                            display_name, description, agent_config_id,
                                            workflow_config_id, webhook_url, settings,
                                            created_by, updated_by)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    """,
                    repository.id, repository.organization_id, repository.github_owner,
                    repository.github_repo, repository.display_name, repository.description,
                    repository.agent_config_id, repository.workflow_config_id,
                    repository.webhook_url, json.dumps(repository.settings),
                    repository.created_by, repository.updated_by
                )
        else:
            self._memory_storage['repositories'][repository.id] = repository.dict()

        logger.info("Repository created", repo_id=repository.id, full_name=repository.full_name)
        return repository

    async def get_repository(self, repo_id: str) -> Optional[Repository]:
        """Get repository by ID"""
        if self.pool:
            async with self.get_connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM repositories WHERE id = $1 AND is_active = true",
                    repo_id
                )
                if row:
                    return Repository(**dict(row))
        else:
            repo_data = self._memory_storage['repositories'].get(repo_id)
            if repo_data:
                return Repository(**repo_data)
        return None

    async def get_repository_by_name(self, owner: str, repo: str) -> Optional[Repository]:
        """Get repository by GitHub owner/repo"""
        if self.pool:
            async with self.get_connection() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM repositories 
                    WHERE github_owner = $1 AND github_repo = $2 AND is_active = true
                    """,
                    owner, repo
                )
                if row:
                    return Repository(**dict(row))
        else:
            for repo_data in self._memory_storage['repositories'].values():
                if (repo_data['github_owner'] == owner and 
                    repo_data['github_repo'] == repo and 
                    repo_data.get('is_active', True)):
                    return Repository(**repo_data)
        return None

    # Agent configuration operations

    async def create_agent_config(self, config: AgentConfigCreate, org_id: str,
                                created_by: str) -> AgentConfig:
        """Create new agent configuration"""
        agent_config = AgentConfig(
            **config.dict(),
            organization_id=org_id,
            created_by=created_by,
            updated_by=created_by
        )

        if self.pool:
            async with self.get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO agent_configs (id, organization_id, name, description,
                                             personality_type, system_prompt, response_style,
                                             context_files, capabilities, max_context_length,
                                             timeout_seconds, settings, created_by, updated_by)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                    """,
                    agent_config.id, agent_config.organization_id, agent_config.name,
                    agent_config.description, agent_config.personality_type.value,
                    agent_config.system_prompt, json.dumps(agent_config.response_style.dict()),
                    agent_config.context_files, [c.value for c in agent_config.capabilities],
                    agent_config.max_context_length, agent_config.timeout_seconds,
                    json.dumps(agent_config.settings), agent_config.created_by,
                    agent_config.updated_by
                )
        else:
            self._memory_storage['agent_configs'][agent_config.id] = agent_config.dict()

        logger.info("Agent config created", config_id=agent_config.id, name=agent_config.name)
        return agent_config

    async def get_agent_config(self, config_id: str) -> Optional[AgentConfig]:
        """Get agent configuration by ID"""
        if self.pool:
            async with self.get_connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM agent_configs WHERE id = $1 AND is_active = true",
                    config_id
                )
                if row:
                    # Convert back to proper types
                    data = dict(row)
                    data['response_style'] = ResponseStyle(**json.loads(data['response_style']))
                    data['capabilities'] = [AgentCapability(c) for c in data['capabilities']]
                    data['personality_type'] = AgentPersonality(data['personality_type'])
                    return AgentConfig(**data)
        else:
            config_data = self._memory_storage['agent_configs'].get(config_id)
            if config_data:
                return AgentConfig(**config_data)
        return None

    async def list_agent_configs(self, org_id: str) -> List[AgentConfig]:
        """List agent configurations for organization"""
        configs = []
        
        if self.pool:
            async with self.get_connection() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM agent_configs 
                    WHERE organization_id = $1 AND is_active = true
                    ORDER BY is_default DESC, name ASC
                    """,
                    org_id
                )
                for row in rows:
                    data = dict(row)
                    data['response_style'] = ResponseStyle(**json.loads(data['response_style']))
                    data['capabilities'] = [AgentCapability(c) for c in data['capabilities']]
                    data['personality_type'] = AgentPersonality(data['personality_type'])
                    configs.append(AgentConfig(**data))
        else:
            for config_data in self._memory_storage['agent_configs'].values():
                if (config_data['organization_id'] == org_id and 
                    config_data.get('is_active', True)):
                    configs.append(AgentConfig(**config_data))

        return configs

    # Permission operations

    async def check_permission(self, user_id: str, repository_id: Optional[str],
                             permission: Permission) -> bool:
        """Check if user has specific permission"""
        user = await self.get_user(user_id)
        if not user:
            return False

        # Check global role permissions
        global_permissions = ROLE_HIERARCHY.get(user.global_role, [])
        if permission in global_permissions:
            return True

        # Check repository-specific permissions if repository specified
        if repository_id:
            repo_permissions = await self.get_repository_permissions(user_id, repository_id)
            if permission in repo_permissions:
                return True

        return False

    async def get_repository_permissions(self, user_id: str, repository_id: str) -> List[Permission]:
        """Get user's permissions for specific repository"""
        permissions = []

        if self.pool:
            async with self.get_connection() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT role, permissions FROM repository_permissions
                    WHERE user_id = $1 AND repository_id = $2 AND is_active = true
                    """,
                    user_id, repository_id
                )
                if row:
                    role_permissions = ROLE_HIERARCHY.get(UserRole(row['role']), [])
                    explicit_permissions = [Permission(p) for p in row['permissions']]
                    permissions = list(set(role_permissions + explicit_permissions))
        else:
            for perm_data in self._memory_storage['repository_permissions'].values():
                if (perm_data['user_id'] == user_id and 
                    perm_data['repository_id'] == repository_id and
                    perm_data.get('is_active', True)):
                    role_permissions = ROLE_HIERARCHY.get(UserRole(perm_data['role']), [])
                    explicit_permissions = [Permission(p) for p in perm_data['permissions']]
                    permissions = list(set(role_permissions + explicit_permissions))
                    break

        return permissions

    # Health and metrics

    async def record_metric(self, config_id: str, config_type: str, 
                          metric_type: str, value: float, 
                          metadata: Dict[str, Any] = None) -> None:
        """Record configuration performance metric"""
        metric = ConfigurationMetrics(
            config_id=config_id,
            config_type=config_type,
            metric_type=metric_type,
            value=value,
            metadata=metadata or {}
        )

        if self.pool:
            async with self.get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO configuration_metrics (config_id, config_type, metric_type, 
                                                      value, metadata)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    metric.config_id, metric.config_type, metric.metric_type,
                    metric.value, json.dumps(metric.metadata)
                )
        else:
            self._memory_storage['metrics'].append(metric.dict())

    async def get_health_status(self) -> List[SystemHealth]:
        """Get system health status"""
        health_checks = []

        # Database connectivity
        try:
            if self.pool:
                async with self.get_connection() as conn:
                    await conn.fetchval("SELECT 1")
            health_checks.append(SystemHealth(
                component="database",
                status="healthy",
                message="Database connection successful"
            ))
        except Exception as e:
            health_checks.append(SystemHealth(
                component="database",
                status="unhealthy",
                message=f"Database connection failed: {str(e)}"
            ))

        # Configuration counts
        try:
            orgs = await self.list_organizations(limit=1000)
            health_checks.append(SystemHealth(
                component="organizations",
                status="healthy",
                metrics={"count": len(orgs)}
            ))
        except Exception as e:
            health_checks.append(SystemHealth(
                component="organizations",
                status="degraded",
                message=f"Failed to count organizations: {str(e)}"
            ))

        return health_checks

    async def cleanup_old_metrics(self, days: int = 30) -> int:
        """Clean up old metrics data"""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        if self.pool:
            async with self.get_connection() as conn:
                result = await conn.execute(
                    "DELETE FROM configuration_metrics WHERE timestamp < $1",
                    cutoff_date
                )
                return int(result.split()[-1])  # Extract count from "DELETE X"
        else:
            initial_count = len(self._memory_storage['metrics'])
            self._memory_storage['metrics'] = [
                m for m in self._memory_storage['metrics']
                if datetime.fromisoformat(m['timestamp']) >= cutoff_date
            ]
            return initial_count - len(self._memory_storage['metrics'])


# Global database service instance
database_service = DatabaseService()