# Configuration Framework Setup Guide

## Overview

This guide walks you through setting up and using the comprehensive configuration framework that transforms the Agentic GitHub Issue Response System into a flexible, multi-tenant platform.

## What's New

The configuration framework adds these powerful capabilities:

### 🏢 **Multi-Organization Support**
- Support for multiple organizations and teams
- Role-based access control with granular permissions
- Organization-level settings and customization

### 🤖 **Agent Personality System**
- 8 built-in agent personalities (Helpful, Technical, Concise, etc.)
- Custom agent configurations with unique behaviors
- Context-aware responses based on agent type

### ⚙️ **Workflow Engine**
- Configurable processing pipelines per task type
- Custom validation rules and conditional branching
- Step-by-step workflow execution with error handling

### 📋 **Template Management**
- Dynamic issue and response templates
- Variable substitution and Jinja2 templating
- Organization and repository-specific customization

### 🔐 **Permission Management**
- Hierarchical user roles (Super Admin, Org Admin, Maintainer, etc.)
- Repository-specific permissions
- Fine-grained access control

## Quick Start

### 1. Environment Setup

Update your `.env` file with configuration framework settings:

```bash
# Copy the new environment template
cp .env.example .env

# Edit your .env file to include:
DATABASE_URL=postgresql://user:password@localhost:5432/agent_config
ENABLE_CONFIGURATION_FRAMEWORK=true
JWT_SECRET_KEY=your-super-secret-jwt-key-change-in-production
```

### 2. Database Setup

For production, set up PostgreSQL:

```bash
# Install PostgreSQL (Ubuntu/Debian)
sudo apt update
sudo apt install postgresql postgresql-contrib

# Create database and user
sudo -u postgres psql
CREATE DATABASE agent_config;
CREATE USER agent_user WITH ENCRYPTED PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE agent_config TO agent_user;
\q

# Update DATABASE_URL in .env
DATABASE_URL=postgresql://agent_user:your_password@localhost:5432/agent_config
```

For development, leave `DATABASE_URL` empty to use in-memory storage.

### 3. Start the Enhanced System

```bash
# Install new dependencies (if needed)
pip install asyncpg jinja2 pyjwt

# Start the server
python main.py
```

### 4. Access the Configuration API

The system now includes comprehensive REST API endpoints:

- **API Documentation**: `http://localhost:8080/docs`
- **Configuration Health**: `http://localhost:8080/api/v1/config/health`
- **Agent Presets**: `http://localhost:8080/api/v1/config/agent-presets`

## Core Concepts

### Organizations

Organizations are the top-level containers for teams and repositories.

```python
# Create organization via API
POST /api/v1/config/organizations
{
    "name": "Acme Corp",
    "slug": "acme-corp",
    "description": "Acme Corporation Development Team"
}
```

### Users and Roles

The system supports hierarchical user roles:

- **Super Admin**: Full system access
- **Org Admin**: Organization management
- **Maintainer**: Repository management
- **Contributor**: Limited repository access
- **User**: Basic usage permissions

### Agent Personalities

Choose from 8 built-in personalities or create custom ones:

1. **Helpful** - Friendly and encouraging
2. **Technical** - Precise and detailed
3. **Concise** - Brief and efficient
4. **Detailed** - Comprehensive analysis
5. **Educational** - Teaching-focused
6. **Professional** - Business-oriented
7. **Creative** - Innovative solutions
8. **Debugging** - Systematic troubleshooting

### Workflows

Create custom processing pipelines:

```json
{
    "name": "Code Review Workflow",
    "task_types": ["Code Analysis", "Code Review"],
    "processing_steps": [
        {
            "name": "validation",
            "stage": "validation",
            "processor_class": "validation"
        },
        {
            "name": "analysis",
            "stage": "analysis", 
            "processor_class": "analysis",
            "depends_on": ["validation"]
        }
    ]
}
```

## Configuration Examples

### 1. Setting Up Your First Organization

```bash
# Create organization
curl -X POST "http://localhost:8080/api/v1/config/organizations" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Development Team",
    "slug": "my-dev-team",
    "description": "Internal development organization"
  }'
```

### 2. Creating a Custom Agent

```bash
# Create custom agent based on Technical personality
curl -X POST "http://localhost:8080/api/v1/config/organizations/{org_id}/agent-configs" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Senior Code Reviewer",
    "personality_type": "technical",
    "system_prompt": "You are a senior software engineer focused on code quality, security, and best practices. Provide detailed technical reviews with specific recommendations.",
    "capabilities": ["code_analysis", "security_review", "performance_optimization"],
    "response_style": {
      "tone": "professional_and_precise",
      "explanation_depth": "comprehensive",
      "include_alternatives": true
    }
  }'
```

### 3. Registering a Repository

```bash
# Register repository with custom agent and workflow
curl -X POST "http://localhost:8080/api/v1/config/organizations/{org_id}/repositories" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "github_owner": "myorg",
    "github_repo": "my-project", 
    "display_name": "My Project",
    "agent_config_id": "custom-agent-id",
    "workflow_config_id": "custom-workflow-id"
  }'
```

### 4. Custom Response Template

```bash
# Create custom completion template
curl -X POST "http://localhost:8080/api/v1/config/organizations/{org_id}/templates" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Code Review Completion",
    "template_type": "completion",
    "content": "## ✅ Code Review Complete\n\nHi {{user_name}}! I'\''ve completed reviewing {{file_count}} files.\n\n### Summary\n{{results_summary}}\n\n### Key Findings\n{% for finding in key_findings %}\n- {{finding}}\n{% endfor %}\n\n**Quality Score:** {{quality_score}}/100",
    "variables": [
      {"name": "user_name", "type": "string", "is_required": true},
      {"name": "file_count", "type": "number", "is_required": true},
      {"name": "results_summary", "type": "string", "is_required": true},
      {"name": "key_findings", "type": "list"},
      {"name": "quality_score", "type": "number"}
    ]
  }'
```

## Migration from Legacy System

### Automatic Migration

The new system maintains backward compatibility:

1. **Existing Issues**: Continue to work with default configurations
2. **Environment Variables**: Legacy settings are still supported
3. **GitHub Integration**: No changes to webhook setup required

### Gradual Migration Steps

1. **Enable Framework**: Set `ENABLE_CONFIGURATION_FRAMEWORK=true`
2. **Create Organization**: Set up your organization via API
3. **Register Repositories**: Add existing repositories to the organization
4. **Customize Agents**: Create custom agent configurations
5. **Set Permissions**: Assign user roles and permissions
6. **Create Templates**: Develop custom response templates

### Configuration Import

You can bulk-import configurations:

```python
# Example: Import existing repository configurations
import asyncio
from src.services.database_service import database_service
from src.models.configuration import OrganizationCreate, RepositoryCreate

async def migrate_repositories():
    # Create organization
    org = await database_service.create_organization(
        OrganizationCreate(
            name="Legacy Migration",
            slug="legacy-org"
        ),
        "admin-user"
    )
    
    # Register repositories
    repos = [
        {"owner": "org1", "repo": "repo1"},
        {"owner": "org1", "repo": "repo2"},
    ]
    
    for repo_info in repos:
        await database_service.create_repository(
            RepositoryCreate(
                github_owner=repo_info["owner"],
                github_repo=repo_info["repo"]
            ),
            org.id,
            "admin-user"
        )
```

## Advanced Configuration

### Custom Workflow Processors

Create custom processing steps:

```python
# src/services/custom_processors.py
from src.services.workflow_engine import BaseProcessor, StepResult, StepStatus

class CustomSecurityProcessor(BaseProcessor):
    async def execute(self, context):
        # Custom security analysis logic
        security_issues = await self.analyze_security(context.parsed_task)
        
        return StepResult(
            step_name=self.name,
            status=StepStatus.COMPLETED,
            output={
                "security_score": security_issues["score"],
                "vulnerabilities": security_issues["issues"]
            }
        )
```

### Custom Agent Capabilities

Extend agent capabilities:

```python
# Add to AgentCapability enum
class CustomAgentCapability(str, Enum):
    CUSTOM_ANALYSIS = "custom_analysis"
    COMPLIANCE_CHECK = "compliance_check"
    COST_ESTIMATION = "cost_estimation"
```

### Database Sharding

For large-scale deployments:

```python
# config/database_config.py
DATABASE_SHARDS = {
    "shard1": "postgresql://user:pass@db1:5432/agent_config",
    "shard2": "postgresql://user:pass@db2:5432/agent_config",
}

# Route organizations to shards based on ID
def get_shard_for_org(org_id: str) -> str:
    shard_index = hash(org_id) % len(DATABASE_SHARDS)
    return list(DATABASE_SHARDS.keys())[shard_index]
```

## Monitoring and Metrics

### Health Monitoring

Monitor configuration framework health:

```bash
# Check overall health
curl "http://localhost:8080/api/v1/config/health"

# Get system summary
curl "http://localhost:8080/api/v1/config/summary" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

### Performance Metrics

Track agent and workflow performance:

```bash
# Get agent performance metrics
curl "http://localhost:8080/api/v1/config/organizations/{org_id}/agent-configs/{config_id}/metrics?days=30" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

### Custom Metrics

Add custom metrics:

```python
# Record custom metrics
await database_service.record_metric(
    config_id="agent-config-id",
    config_type="agent",
    metric_type="custom_success_rate",
    value=95.5,
    metadata={"context": "code_review_tasks"}
)
```

## Security Considerations

### API Authentication

The system uses JWT tokens for API authentication:

```python
# Generate JWT token (implement proper auth flow)
import jwt
from datetime import datetime, timedelta

token = jwt.encode({
    "user_id": "user-id",
    "username": "github-username",
    "exp": datetime.utcnow() + timedelta(hours=24)
}, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
```

### Permission Best Practices

1. **Principle of Least Privilege**: Grant minimum necessary permissions
2. **Regular Audits**: Review user permissions quarterly
3. **Role Segregation**: Separate admin and operational roles
4. **Repository Isolation**: Use repository-specific permissions

### Secret Management

Store sensitive configuration securely:

```bash
# Use environment variables for secrets
export JWT_SECRET_KEY="$(openssl rand -base64 32)"
export DATABASE_PASSWORD="$(openssl rand -base64 32)"

# Or use external secret management
export JWT_SECRET_KEY="$(vault kv get -field=jwt_key secret/agent/config)"
```

## Troubleshooting

### Common Issues

1. **Database Connection Failed**
   ```bash
   # Check PostgreSQL status
   sudo systemctl status postgresql
   
   # Test connection
   psql -h localhost -U agent_user -d agent_config -c "SELECT 1;"
   ```

2. **Permission Denied Errors**
   ```bash
   # Check user permissions
   curl "http://localhost:8080/api/v1/config/organizations/{org_id}/users/{user_id}/permissions" \
     -H "Authorization: Bearer YOUR_JWT_TOKEN"
   ```

3. **Template Rendering Errors**
   ```bash
   # Validate template
   curl -X POST "http://localhost:8080/api/v1/config/templates/validate" \
     -H "Content-Type: application/json" \
     -d '{"content": "Hello {{user_name}}", "variables": [{"name": "user_name", "type": "string"}]}'
   ```

### Debug Mode

Enable debug logging:

```bash
# Set debug mode
DEBUG=true
LOG_LEVEL=DEBUG

# Check logs
tail -f logs/agent.log
```

### Performance Tuning

Optimize for large deployments:

```bash
# Database tuning
# Add to postgresql.conf
shared_buffers = 256MB
effective_cache_size = 1GB
max_connections = 200

# Application tuning
MAX_CONCURRENT_JOBS=10
DATABASE_POOL_SIZE=20
```

## Production Deployment

### Docker Deployment

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
CMD ["python", "main.py"]
```

```yaml
# docker-compose.yml
version: '3.8'
services:
  agent:
    build: .
    ports:
      - "8080:8080"
    environment:
      - DATABASE_URL=postgresql://agent:password@db:5432/agent_config
      - ENABLE_CONFIGURATION_FRAMEWORK=true
    depends_on:
      - db
  
  db:
    image: postgres:15
    environment:
      - POSTGRES_DB=agent_config
      - POSTGRES_USER=agent
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

### Kubernetes Deployment

```yaml
# k8s-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agent-config-system
spec:
  replicas: 3
  selector:
    matchLabels:
      app: agent-config-system
  template:
    metadata:
      labels:
        app: agent-config-system
    spec:
      containers:
      - name: agent
        image: agent-config-system:latest
        ports:
        - containerPort: 8080
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: agent-secrets
              key: database-url
        - name: JWT_SECRET_KEY
          valueFrom:
            secretKeyRef:
              name: agent-secrets
              key: jwt-secret
```

## Support and Community

### Getting Help

1. **Documentation**: Check `/docs` endpoint for API documentation
2. **Health Checks**: Monitor `/api/v1/config/health` for system status
3. **Logs**: Enable debug logging for detailed troubleshooting
4. **GitHub Issues**: Report bugs and feature requests

### Contributing

The configuration framework is designed to be extensible:

1. **Custom Processors**: Add new workflow processing steps
2. **Agent Capabilities**: Extend agent functionality
3. **Template Types**: Create new template categories
4. **Permission Types**: Add granular permission controls

### Roadmap

Upcoming features:

- **Multi-Region Support**: Deploy across multiple regions
- **Advanced Analytics**: ML-powered configuration optimization
- **Integration Hub**: Pre-built integrations with popular tools
- **Enterprise SSO**: SAML and OAuth integration
- **Audit Logging**: Comprehensive audit trail
- **Configuration Versioning**: Track configuration changes over time

---

**Need Help?** Check the API documentation at `/docs` or review the comprehensive analysis document for detailed architecture information.