"""
Simple file-based agent configuration service
"""

import structlog
from typing import Dict, List, Optional, Any
from pathlib import Path

from src.models.configuration import AgentConfig, AgentManager, ResponseStyle

logger = structlog.get_logger()


class AgentConfigService:
    """Manages simple file-based agent configurations"""

    def __init__(self, agents_dir: Path = None):
        self.agent_manager = AgentManager(agents_dir)
        self._context_cache = {}

    async def get_agent_config(self, agent_id: str = None) -> AgentConfig:
        """Get agent configuration by ID, or default if not specified"""
        if agent_id:
            agent = self.agent_manager.get_agent(agent_id)
            if agent:
                logger.info("Loaded agent configuration", agent_id=agent_id, name=agent.name)
                return agent
            else:
                logger.warning("Agent not found, falling back to default", agent_id=agent_id)
        
        # Fall back to default agent
        default_agent = self.agent_manager.get_default_agent()
        logger.info("Using default agent", name=default_agent.name)
        return default_agent

    async def list_available_agents(self) -> Dict[str, str]:
        """List all available agents with their names"""
        agents = self.agent_manager.load_all_agents()
        return {agent_id: agent.name for agent_id, agent in agents.items()}

    async def reload_agents(self) -> None:
        """Reload all agent configurations from disk"""
        self.agent_manager.reload_agents()
        self._context_cache.clear()
        logger.info("Agent configurations reloaded")

    async def get_system_prompt(self, agent_config: AgentConfig, context: Dict[str, Any] = None) -> str:
        """Build complete system prompt with optional context injection"""
        base_prompt = agent_config.system_prompt
        
        if not context:
            return base_prompt
        
        # Add context-specific instructions
        context_additions = []
        
        repository_info = context.get("repository_info", {})
        if repository_info.get("name"):
            context_additions.append(f"Repository: {repository_info['name']}")
        
        if repository_info.get("description"):
            context_additions.append(f"Description: {repository_info['description']}")
        
        if context.get("task_type"):
            context_additions.append(f"Task Type: {context['task_type']}")
        
        # Add capability-specific instructions
        capabilities = agent_config.capabilities
        if capabilities:
            capability_instructions = self._get_capability_instructions(capabilities)
            if capability_instructions:
                context_additions.append(f"Focus Areas: {', '.join(capability_instructions)}")
        
        # Add response style guidance
        style_instructions = self._get_style_instructions(agent_config.response_style)
        if style_instructions:
            context_additions.append(f"Response Style: {style_instructions}")
        
        # Combine prompt with context
        if context_additions:
            enhanced_prompt = f"{base_prompt}\n\nContext:\n" + "\n".join(f"- {addition}" for addition in context_additions)
        else:
            enhanced_prompt = base_prompt
        
        return enhanced_prompt

    async def get_context_files(self, agent_config: AgentConfig) -> List[str]:
        """Get context files specified in agent configuration"""
        context_files = []
        
        for file_pattern in agent_config.context_files:
            # For now, just return the patterns as-is
            # In the future, this could resolve glob patterns
            context_files.append(file_pattern)
        
        logger.debug("Context files loaded", count=len(context_files), files=context_files)
        return context_files

    async def validate_agent_config(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate agent configuration data"""
        errors = []
        warnings = []
        
        # Required fields
        required_fields = ["name", "description", "system_prompt"]
        for field in required_fields:
            if not config_data.get(field):
                errors.append(f"Missing required field: {field}")
        
        # System prompt validation
        system_prompt = config_data.get("system_prompt", "")
        if len(system_prompt.strip()) < 20:
            errors.append("System prompt must be at least 20 characters")
        
        # Timeout validation
        timeout = config_data.get("timeout_seconds", 3600)
        if not isinstance(timeout, int) or timeout < 60 or timeout > 7200:
            warnings.append("Timeout should be between 60 and 7200 seconds")
        
        # Response style validation
        response_style = config_data.get("response_style", {})
        if response_style:
            valid_tones = ["helpful_and_professional", "direct_and_efficient", "systematic_and_analytical"]
            if response_style.get("tone") and response_style["tone"] not in valid_tones:
                warnings.append(f"Unusual tone value: {response_style['tone']}")
            
            valid_emoji_levels = ["none", "minimal", "moderate", "extensive"]
            if response_style.get("emoji_usage") and response_style["emoji_usage"] not in valid_emoji_levels:
                warnings.append(f"Invalid emoji_usage value: {response_style['emoji_usage']}")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }

    def _get_capability_instructions(self, capabilities: List[str]) -> List[str]:
        """Get instructions based on available capabilities"""
        capability_descriptions = {
            "code_analysis": "analyzing code quality and structure",
            "bug_fixing": "identifying and fixing bugs",
            "documentation": "creating comprehensive documentation",
            "testing_strategies": "designing testing approaches",
            "architecture_review": "reviewing system design",
            "performance_optimization": "improving performance",
            "security_review": "identifying security issues",
            "debugging": "systematic troubleshooting",
            "code_generation": "creating new code",
            "deployment_guidance": "helping with deployment",
            "quick_fixes": "providing immediate solutions",
            "error_analysis": "analyzing error patterns",
            "log_analysis": "reviewing log files"
        }
        
        return [capability_descriptions.get(cap, cap) for cap in capabilities if cap in capability_descriptions]

    def _get_style_instructions(self, response_style: ResponseStyle) -> str:
        """Get style instructions from response style configuration"""
        instructions = []
        
        if response_style.tone and response_style.tone != "helpful_and_professional":
            instructions.append(f"tone: {response_style.tone}")
        
        if response_style.emoji_usage and response_style.emoji_usage != "moderate":
            instructions.append(f"emoji usage: {response_style.emoji_usage}")
        
        if response_style.explanation_depth and response_style.explanation_depth != "balanced":
            instructions.append(f"detail level: {response_style.explanation_depth}")
        
        if response_style.max_response_length:
            instructions.append(f"max length: {response_style.max_response_length} characters")
        
        return ", ".join(instructions)

    async def get_agent_info(self, agent_id: str = None) -> Dict[str, Any]:
        """Get information about an agent for display purposes"""
        agent = await self.get_agent_config(agent_id)
        
        return {
            "id": agent_id or "default",
            "name": agent.name,
            "description": agent.description,
            "capabilities": agent.capabilities,
            "response_style": agent.response_style.dict(),
            "timeout_seconds": agent.timeout_seconds,
            "context_files_count": len(agent.context_files),
            "config_file": getattr(agent, 'config_file', None)
        }