"""
Template management system for customizable issue and response templates
"""

import structlog
from typing import Dict, List, Optional, Any
from datetime import datetime
import re
import json
from jinja2 import Environment, BaseLoader, TemplateError, meta

from src.models.configuration import (
    Template, TemplateCreate, TemplateType, TemplateVariable,
    Repository, AgentConfig, User
)
from src.services.database_service import DatabaseService

logger = structlog.get_logger()


class TemplateStringLoader(BaseLoader):
    """Custom Jinja2 loader for template strings"""
    
    def __init__(self, templates: Dict[str, str]):
        self.templates = templates
    
    def get_source(self, environment, template):
        if template in self.templates:
            source = self.templates[template]
            return source, None, lambda: True
        raise TemplateError(f"Template '{template}' not found")


class TemplateManager:
    """Manages customizable templates for issues and responses"""

    def __init__(self, db_service: DatabaseService):
        self.db = db_service
        self.jinja_env = Environment(loader=TemplateStringLoader({}))
        self.default_templates = self._create_default_templates()
        self._template_cache = {}

    def _create_default_templates(self) -> Dict[str, Template]:
        """Create default system templates"""
        
        default_templates = {}
        
        # Progress update template
        progress_template = Template(
            id="default_progress_update",
            organization_id="",
            name="Default Progress Update",
            template_type=TemplateType.PROGRESS_UPDATE,
            description="Standard progress update template",
            content="""## 🔄 Progress Update

Hey {{user_name}}! 👋

I'm currently working on your task: **{{task_summary}}**

### Current Status
- **Progress:** {{progress_percentage}}% complete
- **Current Step:** {{current_step}}
- **Estimated Completion:** {{estimated_completion}}

{% if details %}
### What I'm Doing
{{details}}
{% endif %}

{% if next_steps %}
### Next Steps
{% for step in next_steps %}
- {{step}}
{% endfor %}
{% endif %}

{% if agent_personality == 'helpful' %}
Thanks for your patience! I'm working hard to get this done for you. 😊
{% elif agent_personality == 'technical' %}
Processing continues according to established parameters.
{% elif agent_personality == 'concise' %}
Work in progress. {{progress_percentage}}% done.
{% endif %}

---
*Powered by {{agent_name}} • {{timestamp}}*""",
            variables=[
                TemplateVariable(name="user_name", type="string", description="User's display name", is_required=True),
                TemplateVariable(name="task_summary", type="string", description="Brief task description", is_required=True),
                TemplateVariable(name="progress_percentage", type="number", description="Completion percentage", is_required=True),
                TemplateVariable(name="current_step", type="string", description="Current processing step", is_required=True),
                TemplateVariable(name="estimated_completion", type="string", description="Estimated completion time"),
                TemplateVariable(name="details", type="string", description="Detailed progress information"),
                TemplateVariable(name="next_steps", type="list", description="List of upcoming steps"),
                TemplateVariable(name="agent_name", type="string", description="Agent name", default_value="AI Assistant"),
                TemplateVariable(name="agent_personality", type="string", description="Agent personality type"),
                TemplateVariable(name="timestamp", type="string", description="Current timestamp")
            ],
            is_default=True,
            is_active=True
        )
        default_templates["progress_update"] = progress_template

        # Completion template
        completion_template = Template(
            id="default_completion",
            organization_id="",
            name="Default Task Completion",
            template_type=TemplateType.COMPLETION,
            description="Standard task completion template",
            content="""## ✅ Task Completed Successfully!

Hello {{user_name}}! 🎉

I've successfully completed your task: **{{task_summary}}**

### Summary
{{results_summary}}

{% if code_changes_count > 0 %}
### Changes Made
- **{{code_changes_count}}** code files modified
- **{{execution_time}}** total processing time
{% endif %}

{% if deliverables %}
### Deliverables
{% for deliverable in deliverables %}
- {{deliverable}}
{% endfor %}
{% endif %}

{% if recommendations %}
### Recommendations
{% for recommendation in recommendations %}
- {{recommendation}}
{% endfor %}
{% endif %}

{% if agent_personality == 'helpful' %}
I hope this helps! Feel free to ask if you need any clarification or have follow-up questions. 😊
{% elif agent_personality == 'technical' %}
Implementation complete. All objectives have been satisfied per specifications.
{% elif agent_personality == 'educational' %}
Great learning opportunity! Here are some key concepts covered in this task:
{% for concept in learning_points %}
- {{concept}}
{% endfor %}
{% endif %}

---
*Task completed by {{agent_name}} • {{timestamp}}*""",
            variables=[
                TemplateVariable(name="user_name", type="string", description="User's display name", is_required=True),
                TemplateVariable(name="task_summary", type="string", description="Brief task description", is_required=True),
                TemplateVariable(name="results_summary", type="string", description="Summary of results", is_required=True),
                TemplateVariable(name="code_changes_count", type="number", description="Number of code changes made", default_value=0),
                TemplateVariable(name="execution_time", type="string", description="Total execution time"),
                TemplateVariable(name="deliverables", type="list", description="List of deliverables"),
                TemplateVariable(name="recommendations", type="list", description="List of recommendations"),
                TemplateVariable(name="learning_points", type="list", description="Educational concepts covered"),
                TemplateVariable(name="agent_name", type="string", description="Agent name", default_value="AI Assistant"),
                TemplateVariable(name="agent_personality", type="string", description="Agent personality type"),
                TemplateVariable(name="timestamp", type="string", description="Current timestamp")
            ],
            is_default=True,
            is_active=True
        )
        default_templates["completion"] = completion_template

        # Error response template
        error_template = Template(
            id="default_error_response",
            organization_id="",
            name="Default Error Response",
            template_type=TemplateType.ERROR_RESPONSE,
            description="Standard error response template",
            content="""## ❌ Task Failed

Hi {{user_name}},

I encountered an issue while processing your task: **{{task_summary}}**

### Error Details
**Type:** {{error_type}}
**Message:** {{error_message}}

{% if error_context %}
### Context
{{error_context}}
{% endif %}

### What Happened
{{error_explanation}}

### Recovery Options
{% for option in recovery_options %}
- {{option}}
{% endfor %}

{% if agent_personality == 'helpful' %}
I'm sorry this didn't work out as expected! 😔 Let's try to get this sorted out together.
{% elif agent_personality == 'technical' %}
Error analysis complete. Multiple recovery paths available for retry.
{% elif agent_personality == 'debugging' %}
Systematic analysis indicates the following failure mode: {{failure_mode}}
{% endif %}

{% if support_contact %}
If you need additional help, please contact: {{support_contact}}
{% endif %}

---
*Error reported by {{agent_name}} • {{timestamp}}*""",
            variables=[
                TemplateVariable(name="user_name", type="string", description="User's display name", is_required=True),
                TemplateVariable(name="task_summary", type="string", description="Brief task description", is_required=True),
                TemplateVariable(name="error_type", type="string", description="Type of error", is_required=True),
                TemplateVariable(name="error_message", type="string", description="Error message", is_required=True),
                TemplateVariable(name="error_context", type="string", description="Additional error context"),
                TemplateVariable(name="error_explanation", type="string", description="Human-readable explanation", is_required=True),
                TemplateVariable(name="recovery_options", type="list", description="Available recovery options", is_required=True),
                TemplateVariable(name="failure_mode", type="string", description="Technical failure mode description"),
                TemplateVariable(name="support_contact", type="string", description="Support contact information"),
                TemplateVariable(name="agent_name", type="string", description="Agent name", default_value="AI Assistant"),
                TemplateVariable(name="agent_personality", type="string", description="Agent personality type"),
                TemplateVariable(name="timestamp", type="string", description="Current timestamp")
            ],
            is_default=True,
            is_active=True
        )
        default_templates["error_response"] = error_template

        # Feedback request template
        feedback_template = Template(
            id="default_feedback_request",
            organization_id="",
            name="Default Feedback Request",
            template_type=TemplateType.FEEDBACK_REQUEST,
            description="Standard feedback request template",
            content="""## ❓ Input Needed

Hi {{user_name}}! 👋

I need some clarification to continue with your task: **{{task_summary}}**

### Question
{{feedback_question}}

{% if options %}
### Options
Please choose from the following options:
{% for option in options %}
{{loop.index}}. {{option}}
{% endfor %}
{% endif %}

{% if context %}
### Context
{{context}}
{% endif %}

### How to Respond
{% if response_format %}
{{response_format}}
{% else %}
Simply reply to this comment with your choice or additional information.
{% endif %}

{% if timeout_hours %}
⏰ I'll wait **{{timeout_hours}} hours** for your response before proceeding with default options.
{% endif %}

### Quick Commands
- `/continue` - Continue with current approach
- `/cancel` - Cancel this task
- `/retry` - Start over
- `/escalate` - Get human assistance

{% if agent_personality == 'helpful' %}
Thanks for helping me understand your needs better! 😊
{% elif agent_personality == 'technical' %}
Additional parameters required for optimal processing configuration.
{% elif agent_personality == 'educational' %}
This is a great opportunity to explore different approaches together!
{% endif %}

---
*Feedback requested by {{agent_name}} • {{timestamp}}*""",
            variables=[
                TemplateVariable(name="user_name", type="string", description="User's display name", is_required=True),
                TemplateVariable(name="task_summary", type="string", description="Brief task description", is_required=True),
                TemplateVariable(name="feedback_question", type="string", description="The question being asked", is_required=True),
                TemplateVariable(name="options", type="list", description="Available response options"),
                TemplateVariable(name="context", type="string", description="Additional context for the question"),
                TemplateVariable(name="response_format", type="string", description="Instructions for how to respond"),
                TemplateVariable(name="timeout_hours", type="number", description="Hours to wait for response"),
                TemplateVariable(name="agent_name", type="string", description="Agent name", default_value="AI Assistant"),
                TemplateVariable(name="agent_personality", type="string", description="Agent personality type"),
                TemplateVariable(name="timestamp", type="string", description="Current timestamp")
            ],
            is_default=True,
            is_active=True
        )
        default_templates["feedback_request"] = feedback_template

        return default_templates

    async def create_template(self, org_id: str, template: TemplateCreate,
                            created_by: str) -> Template:
        """Create new template"""
        
        # Validate template content
        await self._validate_template_content(template.content, template.variables)
        
        template_obj = Template(
            **template.dict(),
            organization_id=org_id,
            created_by=created_by,
            updated_by=created_by
        )
        
        # Store in database
        if self.db.pool:
            async with self.db.get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO templates (id, organization_id, name, template_type,
                                         description, content, variables, style_config,
                                         is_default, is_active, tags, created_by, updated_by)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                    """,
                    template_obj.id, template_obj.organization_id, template_obj.name,
                    template_obj.template_type.value, template_obj.description,
                    template_obj.content, [var.dict() for var in template_obj.variables],
                    template_obj.style_config, template_obj.is_default,
                    template_obj.is_active, template_obj.tags,
                    template_obj.created_by, template_obj.updated_by
                )
        else:
            self.db._memory_storage['templates'][template_obj.id] = template_obj.dict()
        
        # Clear cache
        self._clear_template_cache(org_id)
        
        logger.info("Template created", template_id=template_obj.id, name=template_obj.name)
        return template_obj

    async def get_template(self, template_id: str) -> Optional[Template]:
        """Get template by ID"""
        # Check defaults first
        if template_id in self.default_templates:
            return self.default_templates[template_id]
        
        # Check database
        if self.db.pool:
            async with self.db.get_connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM templates WHERE id = $1 AND is_active = true",
                    template_id
                )
                if row:
                    data = dict(row)
                    data['template_type'] = TemplateType(data['template_type'])
                    data['variables'] = [TemplateVariable(**var) for var in data['variables']]
                    return Template(**data)
        else:
            template_data = self.db._memory_storage['templates'].get(template_id)
            if template_data and template_data.get('is_active', True):
                return Template(**template_data)
        
        return None

    async def list_templates(self, org_id: str, template_type: Optional[TemplateType] = None,
                           include_defaults: bool = True) -> List[Template]:
        """List templates for organization"""
        templates = []
        
        # Add organization templates
        if self.db.pool:
            async with self.db.get_connection() as conn:
                query = """
                    SELECT * FROM templates 
                    WHERE organization_id = $1 AND is_active = true
                """
                params = [org_id]
                
                if template_type:
                    query += " AND template_type = $2"
                    params.append(template_type.value)
                
                query += " ORDER BY is_default DESC, name ASC"
                
                rows = await conn.fetch(query, *params)
                for row in rows:
                    data = dict(row)
                    data['template_type'] = TemplateType(data['template_type'])
                    data['variables'] = [TemplateVariable(**var) for var in data['variables']]
                    templates.append(Template(**data))
        else:
            for template_data in self.db._memory_storage['templates'].values():
                if (template_data['organization_id'] == org_id and 
                    template_data.get('is_active', True)):
                    if not template_type or template_data['template_type'] == template_type.value:
                        templates.append(Template(**template_data))
        
        # Add default templates if requested
        if include_defaults:
            for template in self.default_templates.values():
                if not template_type or template.template_type == template_type:
                    # Create copy with org_id
                    default_copy = template.copy()
                    default_copy.organization_id = org_id
                    default_copy.name = f"{template.name} (Default)"
                    templates.append(default_copy)
        
        return templates

    async def get_template_for_type(self, org_id: str, template_type: TemplateType,
                                  repository: Optional[Repository] = None) -> Optional[Template]:
        """Get appropriate template for type and context"""
        
        # Check organization-specific templates first
        org_templates = await self.list_templates(org_id, template_type, include_defaults=False)
        
        # Find repository-specific template if repository provided
        if repository and org_templates:
            repo_specific = [t for t in org_templates if repository.full_name in t.tags]
            if repo_specific:
                return repo_specific[0]
        
        # Find organization default
        org_defaults = [t for t in org_templates if t.is_default]
        if org_defaults:
            return org_defaults[0]
        
        # Fall back to system default
        default_key = template_type.value.replace("_", "_")
        if default_key in self.default_templates:
            default_template = self.default_templates[default_key]
            default_copy = default_template.copy()
            default_copy.organization_id = org_id
            return default_copy
        
        return None

    async def render_template(self, template_id: str, variables: Dict[str, Any],
                            repository: Optional[Repository] = None,
                            agent_config: Optional[AgentConfig] = None,
                            user: Optional[User] = None) -> str:
        """Render template with provided variables"""
        
        template = await self.get_template(template_id)
        if not template:
            raise ValueError(f"Template not found: {template_id}")
        
        # Prepare rendering context
        context = await self._prepare_rendering_context(
            variables, template, repository, agent_config, user
        )
        
        # Validate required variables
        missing_vars = self._check_required_variables(template, context)
        if missing_vars:
            raise ValueError(f"Missing required variables: {', '.join(missing_vars)}")
        
        try:
            # Render template
            jinja_template = self.jinja_env.from_string(template.content)
            rendered = jinja_template.render(**context)
            
            logger.info(
                "Template rendered",
                template_id=template_id,
                variables_count=len(context),
                output_length=len(rendered)
            )
            
            return rendered
            
        except TemplateError as e:
            logger.error("Template rendering failed", template_id=template_id, error=str(e))
            raise ValueError(f"Template rendering error: {str(e)}")

    async def render_template_by_type(self, org_id: str, template_type: TemplateType,
                                    variables: Dict[str, Any],
                                    repository: Optional[Repository] = None,
                                    agent_config: Optional[AgentConfig] = None,
                                    user: Optional[User] = None) -> str:
        """Render template by type using organization defaults"""
        
        template = await self.get_template_for_type(org_id, template_type, repository)
        if not template:
            raise ValueError(f"No template found for type: {template_type}")
        
        return await self.render_template(template.id, variables, repository, agent_config, user)

    async def validate_template(self, content: str, variables: List[TemplateVariable]) -> Dict[str, Any]:
        """Validate template content and variables"""
        result = {
            'is_valid': True,
            'errors': [],
            'warnings': [],
            'used_variables': [],
            'undefined_variables': []
        }
        
        try:
            # Parse template to find variables
            jinja_template = self.jinja_env.from_string(content)
            ast = self.jinja_env.parse(content)
            used_vars = meta.find_undeclared_variables(ast)
            result['used_variables'] = list(used_vars)
            
            # Check for undefined variables
            defined_vars = {var.name for var in variables}
            undefined = used_vars - defined_vars
            if undefined:
                result['undefined_variables'] = list(undefined)
                result['warnings'].append(f"Undefined variables: {', '.join(undefined)}")
            
            # Check for unused variable definitions
            unused = defined_vars - used_vars
            if unused:
                result['warnings'].append(f"Unused variable definitions: {', '.join(unused)}")
            
            # Test template rendering with sample data
            sample_context = self._generate_sample_context(variables)
            jinja_template.render(**sample_context)
            
        except TemplateError as e:
            result['is_valid'] = False
            result['errors'].append(f"Template syntax error: {str(e)}")
        except Exception as e:
            result['is_valid'] = False
            result['errors'].append(f"Template validation error: {str(e)}")
        
        return result

    async def _prepare_rendering_context(self, variables: Dict[str, Any], template: Template,
                                       repository: Optional[Repository] = None,
                                       agent_config: Optional[AgentConfig] = None,
                                       user: Optional[User] = None) -> Dict[str, Any]:
        """Prepare complete rendering context"""
        
        context = variables.copy()
        
        # Add default values for missing variables
        for var in template.variables:
            if var.name not in context and var.default_value is not None:
                context[var.name] = var.default_value
        
        # Add automatic context variables
        context['timestamp'] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        if repository:
            context.setdefault('repository_name', repository.full_name)
            context.setdefault('repository_description', repository.description or "")
        
        if agent_config:
            context.setdefault('agent_name', agent_config.name)
            context.setdefault('agent_personality', agent_config.personality_type.value)
        
        if user:
            context.setdefault('user_name', user.display_name or user.github_username)
            context.setdefault('user_github', user.github_username)
        
        return context

    def _check_required_variables(self, template: Template, context: Dict[str, Any]) -> List[str]:
        """Check for missing required variables"""
        missing = []
        for var in template.variables:
            if var.is_required and var.name not in context:
                missing.append(var.name)
        return missing

    def _generate_sample_context(self, variables: List[TemplateVariable]) -> Dict[str, Any]:
        """Generate sample context for template validation"""
        context = {}
        
        for var in variables:
            if var.default_value is not None:
                context[var.name] = var.default_value
            elif var.type == "string":
                context[var.name] = "sample_string"
            elif var.type == "number":
                context[var.name] = 42
            elif var.type == "boolean":
                context[var.name] = True
            elif var.type == "list":
                context[var.name] = ["item1", "item2"]
            elif var.type == "object":
                context[var.name] = {"key": "value"}
            else:
                context[var.name] = "sample_value"
        
        return context

    async def _validate_template_content(self, content: str, variables: List[TemplateVariable]):
        """Validate template content before creation"""
        validation_result = await self.validate_template(content, variables)
        
        if not validation_result['is_valid']:
            raise ValueError(f"Invalid template: {'; '.join(validation_result['errors'])}")

    def _clear_template_cache(self, org_id: str):
        """Clear template cache for organization"""
        keys_to_remove = [key for key in self._template_cache.keys() if key.startswith(f"{org_id}:")]
        for key in keys_to_remove:
            del self._template_cache[key]

    async def get_template_usage_metrics(self, template_id: str, days: int = 30) -> Dict[str, Any]:
        """Get usage metrics for template"""
        # This would integrate with the metrics system
        return {
            "template_id": template_id,
            "period_days": days,
            "render_count": 0,
            "success_rate": 100.0,
            "average_render_time": 0.0,
            "most_common_variables": [],
            "error_count": 0
        }

    async def duplicate_template(self, template_id: str, new_name: str,
                               org_id: str, created_by: str) -> Template:
        """Duplicate existing template"""
        original = await self.get_template(template_id)
        if not original:
            raise ValueError(f"Template not found: {template_id}")
        
        # Create new template based on original
        template_create = TemplateCreate(
            name=new_name,
            template_type=original.template_type,
            description=f"Copy of {original.name}",
            content=original.content,
            variables=original.variables,
            style_config=original.style_config,
            tags=original.tags
        )
        
        return await self.create_template(org_id, template_create, created_by)