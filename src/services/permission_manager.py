"""
Permission management system for the configuration framework
Handles role-based access control and user permissions
"""

import structlog
from typing import Dict, List, Optional, Set, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from src.models.configuration import (
    User, UserRole, Permission, Repository, Organization,
    OrganizationMembership, RepositoryPermission, PermissionCheck,
    ROLE_HIERARCHY
)
from src.services.database_service import DatabaseService

logger = structlog.get_logger()


class PermissionScope(str, Enum):
    """Permission scope levels"""
    GLOBAL = "global"
    ORGANIZATION = "organization"
    REPOSITORY = "repository"


@dataclass
class PermissionContext:
    """Context for permission evaluation"""
    user_id: str
    repository_id: Optional[str] = None
    organization_id: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    action: Optional[str] = None
    metadata: Dict[str, any] = None


class PermissionManager:
    """Manages user permissions and role-based access control"""

    def __init__(self, db_service: DatabaseService):
        self.db = db_service
        self._permission_cache = {}
        self._cache_ttl = timedelta(minutes=15)
        self._last_cache_clean = datetime.utcnow()

    async def check_permission(self, user_id: str, permission: Permission,
                             repository_id: Optional[str] = None,
                             organization_id: Optional[str] = None) -> PermissionCheck:
        """
        Check if user has specific permission
        Returns detailed permission check result
        """
        cache_key = f"{user_id}:{permission.value}:{repository_id}:{organization_id}"
        
        # Check cache first
        if cache_key in self._permission_cache:
            cached_result, cached_time = self._permission_cache[cache_key]
            if datetime.utcnow() - cached_time < self._cache_ttl:
                logger.debug("Permission check cache hit", user_id=user_id, permission=permission)
                return cached_result

        # Clean cache periodically
        await self._clean_cache()

        result = await self._evaluate_permission(user_id, permission, repository_id, organization_id)
        
        # Cache the result
        self._permission_cache[cache_key] = (result, datetime.utcnow())
        
        logger.info(
            "Permission checked",
            user_id=user_id,
            permission=permission,
            granted=result.granted,
            repository_id=repository_id,
            organization_id=organization_id
        )
        
        return result

    async def _evaluate_permission(self, user_id: str, permission: Permission,
                                 repository_id: Optional[str] = None,
                                 organization_id: Optional[str] = None) -> PermissionCheck:
        """Evaluate permission using hierarchy and explicit grants"""
        
        user = await self.db.get_user(user_id)
        if not user or not user.is_active:
            return PermissionCheck(
                user_id=user_id,
                repository_id=repository_id,
                permission=permission,
                granted=False,
                reason="User not found or inactive"
            )

        # Check global role permissions
        global_permissions = ROLE_HIERARCHY.get(user.global_role, [])
        if permission in global_permissions:
            return PermissionCheck(
                user_id=user_id,
                repository_id=repository_id,
                permission=permission,
                granted=True,
                reason=f"Granted by global role: {user.global_role.value}"
            )

        # Check organization-level permissions
        if organization_id:
            org_granted, org_reason = await self._check_organization_permission(
                user_id, organization_id, permission
            )
            if org_granted:
                return PermissionCheck(
                    user_id=user_id,
                    repository_id=repository_id,
                    permission=permission,
                    granted=True,
                    reason=org_reason
                )

        # Check repository-level permissions
        if repository_id:
            repo_granted, repo_reason = await self._check_repository_permission(
                user_id, repository_id, permission
            )
            if repo_granted:
                return PermissionCheck(
                    user_id=user_id,
                    repository_id=repository_id,
                    permission=permission,
                    granted=True,
                    reason=repo_reason
                )

        return PermissionCheck(
            user_id=user_id,
            repository_id=repository_id,
            permission=permission,
            granted=False,
            reason="Permission not granted by any role or explicit grant"
        )

    async def _check_organization_permission(self, user_id: str, organization_id: str,
                                           permission: Permission) -> Tuple[bool, str]:
        """Check organization-level permission"""
        membership = await self._get_organization_membership(user_id, organization_id)
        if not membership:
            return False, "Not a member of organization"

        # Check role permissions
        role_permissions = ROLE_HIERARCHY.get(membership.role, [])
        if permission in role_permissions:
            return True, f"Granted by organization role: {membership.role.value}"

        # Check explicit permissions
        if permission in membership.permissions:
            return True, "Granted by explicit organization permission"

        return False, "Organization permission not found"

    async def _check_repository_permission(self, user_id: str, repository_id: str,
                                         permission: Permission) -> Tuple[bool, str]:
        """Check repository-level permission"""
        repo_permission = await self._get_repository_permission(user_id, repository_id)
        if not repo_permission:
            return False, "No repository permissions found"

        # Check role permissions
        role_permissions = ROLE_HIERARCHY.get(repo_permission.role, [])
        if permission in role_permissions:
            return True, f"Granted by repository role: {repo_permission.role.value}"

        # Check explicit permissions
        if permission in repo_permission.permissions:
            return True, "Granted by explicit repository permission"

        return False, "Repository permission not found"

    async def get_user_permissions(self, user_id: str, 
                                 repository_id: Optional[str] = None,
                                 organization_id: Optional[str] = None) -> List[Permission]:
        """Get all permissions for user in given context"""
        user = await self.db.get_user(user_id)
        if not user or not user.is_active:
            return []

        permissions = set()

        # Add global role permissions
        global_permissions = ROLE_HIERARCHY.get(user.global_role, [])
        permissions.update(global_permissions)

        # Add organization permissions
        if organization_id:
            membership = await self._get_organization_membership(user_id, organization_id)
            if membership:
                org_role_permissions = ROLE_HIERARCHY.get(membership.role, [])
                permissions.update(org_role_permissions)
                permissions.update(membership.permissions)

        # Add repository permissions
        if repository_id:
            repo_permission = await self._get_repository_permission(user_id, repository_id)
            if repo_permission:
                repo_role_permissions = ROLE_HIERARCHY.get(repo_permission.role, [])
                permissions.update(repo_role_permissions)
                permissions.update(repo_permission.permissions)

        return list(permissions)

    async def grant_permission(self, user_id: str, permission: Permission,
                             repository_id: Optional[str] = None,
                             organization_id: Optional[str] = None,
                             granted_by: str = None) -> bool:
        """Grant explicit permission to user"""
        try:
            if repository_id:
                await self._grant_repository_permission(user_id, repository_id, permission, granted_by)
            elif organization_id:
                await self._grant_organization_permission(user_id, organization_id, permission, granted_by)
            else:
                logger.warning("Cannot grant permission without repository or organization context")
                return False

            # Invalidate cache
            await self._invalidate_user_cache(user_id)

            logger.info(
                "Permission granted",
                user_id=user_id,
                permission=permission,
                repository_id=repository_id,
                organization_id=organization_id,
                granted_by=granted_by
            )
            return True

        except Exception as e:
            logger.error("Failed to grant permission", error=str(e))
            return False

    async def revoke_permission(self, user_id: str, permission: Permission,
                              repository_id: Optional[str] = None,
                              organization_id: Optional[str] = None,
                              revoked_by: str = None) -> bool:
        """Revoke explicit permission from user"""
        try:
            if repository_id:
                await self._revoke_repository_permission(user_id, repository_id, permission, revoked_by)
            elif organization_id:
                await self._revoke_organization_permission(user_id, organization_id, permission, revoked_by)
            else:
                logger.warning("Cannot revoke permission without repository or organization context")
                return False

            # Invalidate cache
            await self._invalidate_user_cache(user_id)

            logger.info(
                "Permission revoked",
                user_id=user_id,
                permission=permission,
                repository_id=repository_id,
                organization_id=organization_id,
                revoked_by=revoked_by
            )
            return True

        except Exception as e:
            logger.error("Failed to revoke permission", error=str(e))
            return False

    async def set_user_role(self, user_id: str, role: UserRole,
                          repository_id: Optional[str] = None,
                          organization_id: Optional[str] = None,
                          set_by: str = None) -> bool:
        """Set user role in repository or organization"""
        try:
            if repository_id:
                await self._set_repository_role(user_id, repository_id, role, set_by)
            elif organization_id:
                await self._set_organization_role(user_id, organization_id, role, set_by)
            else:
                # Set global role
                await self._set_global_role(user_id, role, set_by)

            # Invalidate cache
            await self._invalidate_user_cache(user_id)

            logger.info(
                "User role updated",
                user_id=user_id,
                role=role,
                repository_id=repository_id,
                organization_id=organization_id,
                set_by=set_by
            )
            return True

        except Exception as e:
            logger.error("Failed to set user role", error=str(e))
            return False

    async def add_user_to_organization(self, user_id: str, organization_id: str,
                                     role: UserRole = UserRole.USER,
                                     added_by: str = None) -> bool:
        """Add user to organization with specified role"""
        try:
            membership = OrganizationMembership(
                organization_id=organization_id,
                user_id=user_id,
                role=role,
                permissions=[],
                joined_at=datetime.utcnow(),
                is_active=True
            )

            # Store in database
            if self.db.pool:
                async with self.db.get_connection() as conn:
                    await conn.execute(
                        """
                        INSERT INTO organization_memberships (organization_id, user_id, role, permissions)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (organization_id, user_id) 
                        DO UPDATE SET role = EXCLUDED.role, is_active = true
                        """,
                        organization_id, user_id, role.value, []
                    )
            else:
                key = f"{organization_id}:{user_id}"
                self.db._memory_storage['organization_memberships'][key] = membership.dict()

            # Invalidate cache
            await self._invalidate_user_cache(user_id)

            logger.info(
                "User added to organization",
                user_id=user_id,
                organization_id=organization_id,
                role=role,
                added_by=added_by
            )
            return True

        except Exception as e:
            logger.error("Failed to add user to organization", error=str(e))
            return False

    async def add_user_to_repository(self, user_id: str, repository_id: str,
                                   role: UserRole = UserRole.USER,
                                   added_by: str = None) -> bool:
        """Add user to repository with specified role"""
        try:
            permission = RepositoryPermission(
                repository_id=repository_id,
                user_id=user_id,
                role=role,
                permissions=[],
                granted_at=datetime.utcnow(),
                granted_by=added_by,
                is_active=True
            )

            # Store in database
            if self.db.pool:
                async with self.db.get_connection() as conn:
                    await conn.execute(
                        """
                        INSERT INTO repository_permissions (repository_id, user_id, role, permissions, granted_by)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (repository_id, user_id)
                        DO UPDATE SET role = EXCLUDED.role, is_active = true, granted_by = EXCLUDED.granted_by
                        """,
                        repository_id, user_id, role.value, [], added_by
                    )
            else:
                key = f"{repository_id}:{user_id}"
                self.db._memory_storage['repository_permissions'][key] = permission.dict()

            # Invalidate cache
            await self._invalidate_user_cache(user_id)

            logger.info(
                "User added to repository",
                user_id=user_id,
                repository_id=repository_id,
                role=role,
                added_by=added_by
            )
            return True

        except Exception as e:
            logger.error("Failed to add user to repository", error=str(e))
            return False

    async def get_role_permissions(self, role: UserRole) -> List[Permission]:
        """Get default permissions for role"""
        return ROLE_HIERARCHY.get(role, [])

    async def get_user_repositories(self, user_id: str, organization_id: Optional[str] = None) -> List[Repository]:
        """Get repositories user has access to"""
        repositories = []

        try:
            if self.db.pool:
                async with self.db.get_connection() as conn:
                    query = """
                        SELECT DISTINCT r.* FROM repositories r
                        LEFT JOIN repository_permissions rp ON r.id = rp.repository_id
                        WHERE (rp.user_id = $1 AND rp.is_active = true)
                        OR r.organization_id IN (
                            SELECT om.organization_id FROM organization_memberships om
                            WHERE om.user_id = $1 AND om.is_active = true
                        )
                    """
                    params = [user_id]
                    
                    if organization_id:
                        query += " AND r.organization_id = $2"
                        params.append(organization_id)
                    
                    query += " ORDER BY r.display_name, r.github_repo"
                    
                    rows = await conn.fetch(query, *params)
                    repositories = [Repository(**dict(row)) for row in rows]
            else:
                # In-memory implementation
                for repo_data in self.db._memory_storage['repositories'].values():
                    repo = Repository(**repo_data)
                    
                    # Check if user has repository-level access
                    repo_perm_key = f"{repo.id}:{user_id}"
                    has_repo_access = repo_perm_key in self.db._memory_storage['repository_permissions']
                    
                    # Check if user has organization-level access
                    org_member_key = f"{repo.organization_id}:{user_id}"
                    has_org_access = org_member_key in self.db._memory_storage['organization_memberships']
                    
                    if has_repo_access or has_org_access:
                        if not organization_id or repo.organization_id == organization_id:
                            repositories.append(repo)

        except Exception as e:
            logger.error("Failed to get user repositories", error=str(e))

        return repositories

    # Private helper methods

    async def _get_organization_membership(self, user_id: str, organization_id: str) -> Optional[OrganizationMembership]:
        """Get user's organization membership"""
        if self.db.pool:
            async with self.db.get_connection() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM organization_memberships 
                    WHERE user_id = $1 AND organization_id = $2 AND is_active = true
                    """,
                    user_id, organization_id
                )
                if row:
                    data = dict(row)
                    data['permissions'] = [Permission(p) for p in data['permissions']]
                    data['role'] = UserRole(data['role'])
                    return OrganizationMembership(**data)
        else:
            key = f"{organization_id}:{user_id}"
            membership_data = self.db._memory_storage['organization_memberships'].get(key)
            if membership_data and membership_data.get('is_active', True):
                return OrganizationMembership(**membership_data)
        return None

    async def _get_repository_permission(self, user_id: str, repository_id: str) -> Optional[RepositoryPermission]:
        """Get user's repository permission"""
        if self.db.pool:
            async with self.db.get_connection() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM repository_permissions 
                    WHERE user_id = $1 AND repository_id = $2 AND is_active = true
                    """,
                    user_id, repository_id
                )
                if row:
                    data = dict(row)
                    data['permissions'] = [Permission(p) for p in data['permissions']]
                    data['role'] = UserRole(data['role'])
                    return RepositoryPermission(**data)
        else:
            key = f"{repository_id}:{user_id}"
            perm_data = self.db._memory_storage['repository_permissions'].get(key)
            if perm_data and perm_data.get('is_active', True):
                return RepositoryPermission(**perm_data)
        return None

    async def _grant_repository_permission(self, user_id: str, repository_id: str,
                                         permission: Permission, granted_by: str):
        """Grant repository-specific permission"""
        current_perms = await self._get_repository_permission(user_id, repository_id)
        if not current_perms:
            # Create new repository permission entry
            await self.add_user_to_repository(user_id, repository_id, UserRole.USER, granted_by)
            current_perms = await self._get_repository_permission(user_id, repository_id)

        if current_perms and permission not in current_perms.permissions:
            new_permissions = current_perms.permissions + [permission]
            
            if self.db.pool:
                async with self.db.get_connection() as conn:
                    await conn.execute(
                        """
                        UPDATE repository_permissions 
                        SET permissions = $1, granted_by = $2
                        WHERE user_id = $3 AND repository_id = $4
                        """,
                        [p.value for p in new_permissions], granted_by, user_id, repository_id
                    )
            else:
                key = f"{repository_id}:{user_id}"
                if key in self.db._memory_storage['repository_permissions']:
                    self.db._memory_storage['repository_permissions'][key]['permissions'] = [
                        p.value for p in new_permissions
                    ]

    async def _invalidate_user_cache(self, user_id: str):
        """Invalidate all cached permissions for user"""
        keys_to_remove = [key for key in self._permission_cache.keys() if key.startswith(f"{user_id}:")]
        for key in keys_to_remove:
            del self._permission_cache[key]

    async def _clean_cache(self):
        """Clean expired cache entries"""
        now = datetime.utcnow()
        if now - self._last_cache_clean > self._cache_ttl:
            expired_keys = []
            for key, (result, cached_time) in self._permission_cache.items():
                if now - cached_time > self._cache_ttl:
                    expired_keys.append(key)
            
            for key in expired_keys:
                del self._permission_cache[key]
            
            self._last_cache_clean = now
            logger.debug("Permission cache cleaned", expired_count=len(expired_keys))