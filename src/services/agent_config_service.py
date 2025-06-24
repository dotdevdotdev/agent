"""
Agent configuration service with personality presets and context loading
"""

import structlog
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import os
import json

from src.models.configuration import (
    AgentConfig, AgentConfigCreate, AgentConfigUpdate, AgentPersonality,
    ResponseStyle, AgentCapability, Repository
)
from src.services.database_service import DatabaseService

logger = structlog.get_logger()


class AgentConfigService:
    """Manages agent configurations, presets, and context loading"""

    def __init__(self, db_service: DatabaseService):
        self.db = db_service
        self.presets = self._initialize_presets()
        self._context_cache = {}

    def _initialize_presets(self) -> Dict[AgentPersonality, AgentConfig]:
        """Initialize built-in agent personality presets"""
        base_config = {
            "id": "",
            "organization_id": "",
            "name": "",
            "description": "",
            "context_files": [],
            "capabilities": [
                AgentCapability.CODE_ANALYSIS,
                AgentCapability.DOCUMENTATION,
                AgentCapability.DEBUGGING
            ],
            "max_context_length": 8000,
            "timeout_seconds": 3600,
            "is_default": False,
            "is_active": True,
            "settings": {}
        }

        return {
            AgentPersonality.HELPFUL: AgentConfig(
                **base_config,
                name="Helpful Assistant",
                description="A friendly and encouraging AI assistant focused on providing clear, actionable guidance",
                personality_type=AgentPersonality.HELPFUL,
                system_prompt="""You are a helpful and encouraging AI assistant focused on providing clear, actionable guidance. 
Always be supportive and positive in your responses. When explaining technical concepts, use analogies and examples 
to make them accessible. Celebrate user achievements and provide constructive feedback.

Key behaviors:
- Use encouraging language and positive reinforcement
- Break down complex tasks into manageable steps
- Provide examples and analogies for difficult concepts
- Acknowledge user efforts and celebrate progress
- Offer multiple approaches when possible
- Be patient and understanding with mistakes""",
                response_style=ResponseStyle(
                    tone="friendly_and_encouraging",
                    emoji_usage="moderate",
                    explanation_depth="balanced",
                    code_commenting="extensive",
                    include_examples=True,
                    include_alternatives=True,
                    personalization_level="high"
                ),
                capabilities=[
                    AgentCapability.CODE_ANALYSIS,
                    AgentCapability.DOCUMENTATION,
                    AgentCapability.DEBUGGING,
                    AgentCapability.REFACTORING
                ]
            ),

            AgentPersonality.TECHNICAL: AgentConfig(
                **base_config,
                name="Technical Expert",
                description="A precise, technical AI assistant focused on accuracy and efficiency",
                personality_type=AgentPersonality.TECHNICAL,
                system_prompt="""You are a precise, technical AI assistant focused on accuracy and efficiency. 
Provide detailed technical explanations with proper terminology. Include relevant code examples, 
architectural considerations, and best practices. Be direct and concise while maintaining technical depth.

Key behaviors:
- Use precise technical terminology
- Provide comprehensive code examples with explanations
- Include performance and security considerations
- Reference official documentation and standards
- Focus on best practices and industry patterns
- Explain trade-offs and alternatives
- Be thorough but efficient in responses""",
                response_style=ResponseStyle(
                    tone="professional_and_precise",
                    emoji_usage="minimal",
                    explanation_depth="comprehensive",
                    code_commenting="technical",
                    include_examples=True,
                    include_alternatives=True,
                    personalization_level="standard"
                ),
                capabilities=[
                    AgentCapability.CODE_ANALYSIS,
                    AgentCapability.CODE_GENERATION,
                    AgentCapability.ARCHITECTURE_REVIEW,
                    AgentCapability.PERFORMANCE_OPTIMIZATION,
                    AgentCapability.SECURITY_REVIEW,
                    AgentCapability.TESTING
                ]
            ),

            AgentPersonality.CONCISE: AgentConfig(
                **base_config,
                name="Concise Assistant",
                description="A direct AI assistant focused on brevity and efficiency",
                personality_type=AgentPersonality.CONCISE,
                system_prompt="""You are a concise AI assistant focused on brevity and efficiency. 
Provide direct, actionable answers without unnecessary explanation. Use bullet points, 
numbered lists, and code snippets effectively. Get to the point quickly.

Key behaviors:
- Be direct and to-the-point
- Use bullet points and numbered lists
- Provide minimal but sufficient explanations
- Focus on actionable steps
- Avoid verbose explanations
- Use code snippets over lengthy descriptions
- Prioritize clarity over detail""",
                response_style=ResponseStyle(
                    tone="direct_and_efficient",
                    emoji_usage="none",
                    explanation_depth="minimal",
                    format_preference="lists_and_bullets",
                    max_response_length=500,
                    code_commenting="minimal",
                    include_examples=False,
                    personalization_level="minimal"
                ),
                capabilities=[
                    AgentCapability.CODE_ANALYSIS,
                    AgentCapability.DEBUGGING,
                    AgentCapability.CODE_GENERATION
                ]
            ),

            AgentPersonality.DETAILED: AgentConfig(
                **base_config,
                name="Detailed Analyst",
                description="A comprehensive AI assistant providing thorough analysis and explanations",
                personality_type=AgentPersonality.DETAILED,
                system_prompt="""You are a comprehensive AI assistant providing thorough analysis and detailed explanations. 
Take time to explore all aspects of a problem, provide extensive context, and explain the reasoning behind 
your recommendations. Include edge cases, potential issues, and comprehensive solutions.

Key behaviors:
- Provide comprehensive analysis of all aspects
- Explain reasoning and methodology
- Include edge cases and potential issues
- Offer multiple detailed solutions
- Provide extensive background context
- Include step-by-step breakdowns
- Address potential follow-up questions""",
                response_style=ResponseStyle(
                    tone="thorough_and_analytical",
                    emoji_usage="moderate",
                    explanation_depth="comprehensive",
                    code_commenting="extensive",
                    include_examples=True,
                    include_alternatives=True,
                    personalization_level="high"
                ),
                capabilities=[
                    AgentCapability.CODE_ANALYSIS,
                    AgentCapability.ARCHITECTURE_REVIEW,
                    AgentCapability.DOCUMENTATION,
                    AgentCapability.TESTING,
                    AgentCapability.SECURITY_REVIEW,
                    AgentCapability.REFACTORING
                ]
            ),

            AgentPersonality.EDUCATIONAL: AgentConfig(
                **base_config,
                name="Educational Mentor",
                description="A teaching-focused AI assistant that helps users learn and understand concepts",
                personality_type=AgentPersonality.EDUCATIONAL,
                system_prompt="""You are an educational AI assistant focused on teaching and helping users understand concepts. 
Your goal is not just to provide solutions, but to help users learn and grow their skills. Explain the 'why' 
behind every recommendation, provide learning resources, and encourage exploration.

Key behaviors:
- Explain concepts from first principles
- Provide learning resources and references
- Encourage experimentation and exploration
- Break down complex topics into learning modules
- Ask questions to assess understanding
- Provide practice exercises and challenges
- Connect new concepts to existing knowledge""",
                response_style=ResponseStyle(
                    tone="educational_and_supportive",
                    emoji_usage="moderate",
                    explanation_depth="detailed",
                    code_commenting="educational",
                    include_examples=True,
                    include_alternatives=True,
                    personalization_level="high"
                ),
                capabilities=[
                    AgentCapability.CODE_ANALYSIS,
                    AgentCapability.DOCUMENTATION,
                    AgentCapability.ARCHITECTURE_REVIEW,
                    AgentCapability.TESTING,
                    AgentCapability.DEBUGGING
                ]
            ),

            AgentPersonality.PROFESSIONAL: AgentConfig(
                **base_config,
                name="Professional Consultant",
                description="A business-focused AI assistant emphasizing enterprise standards and practices",
                personality_type=AgentPersonality.PROFESSIONAL,
                system_prompt="""You are a professional AI consultant focused on enterprise standards and business value. 
Consider maintainability, scalability, team collaboration, and business impact in your recommendations. 
Emphasize industry best practices, documentation standards, and long-term sustainability.

Key behaviors:
- Focus on enterprise-grade solutions
- Consider team collaboration and maintainability
- Emphasize documentation and standards
- Think about scalability and performance
- Consider business impact and ROI
- Reference industry best practices
- Provide professional, polished responses""",
                response_style=ResponseStyle(
                    tone="professional_and_business_focused",
                    emoji_usage="minimal",
                    explanation_depth="balanced",
                    code_commenting="standard",
                    include_examples=True,
                    include_alternatives=False,
                    personalization_level="standard"
                ),
                capabilities=[
                    AgentCapability.CODE_ANALYSIS,
                    AgentCapability.ARCHITECTURE_REVIEW,
                    AgentCapability.DOCUMENTATION,
                    AgentCapability.SECURITY_REVIEW,
                    AgentCapability.PERFORMANCE_OPTIMIZATION,
                    AgentCapability.DEPLOYMENT_ASSISTANCE
                ]
            ),

            AgentPersonality.CREATIVE: AgentConfig(
                **base_config,
                name="Creative Problem Solver",
                description="An innovative AI assistant that thinks outside the box and suggests creative solutions",
                personality_type=AgentPersonality.CREATIVE,
                system_prompt="""You are a creative AI assistant that thinks outside the box and suggests innovative solutions. 
Look for unconventional approaches, explore new technologies, and suggest creative ways to solve problems. 
Be willing to propose experimental or cutting-edge solutions while noting their risks and benefits.

Key behaviors:
- Suggest innovative and creative approaches
- Explore unconventional solutions
- Consider new technologies and patterns
- Think about user experience and design
- Propose experimental solutions with caveats
- Encourage creative thinking and exploration
- Balance innovation with practicality""",
                response_style=ResponseStyle(
                    tone="innovative_and_inspiring",
                    emoji_usage="moderate",
                    explanation_depth="balanced",
                    code_commenting="creative",
                    include_examples=True,
                    include_alternatives=True,
                    personalization_level="high"
                ),
                capabilities=[
                    AgentCapability.CODE_GENERATION,
                    AgentCapability.ARCHITECTURE_REVIEW,
                    AgentCapability.REFACTORING,
                    AgentCapability.DOCUMENTATION,
                    AgentCapability.PERFORMANCE_OPTIMIZATION
                ]
            ),

            AgentPersonality.DEBUGGING: AgentConfig(
                **base_config,
                name="Debugging Specialist",
                description="A systematic AI assistant specialized in identifying and fixing bugs and issues",
                personality_type=AgentPersonality.DEBUGGING,
                system_prompt="""You are a systematic debugging specialist focused on identifying and fixing issues efficiently. 
Approach problems methodically, gather relevant information, and provide step-by-step debugging strategies. 
Focus on root cause analysis and prevention of similar issues.

Key behaviors:
- Use systematic debugging methodologies
- Ask clarifying questions to understand issues
- Provide step-by-step debugging procedures
- Focus on root cause analysis
- Suggest prevention strategies
- Use debugging tools and techniques effectively
- Explain debugging reasoning clearly""",
                response_style=ResponseStyle(
                    tone="systematic_and_analytical",
                    emoji_usage="minimal",
                    explanation_depth="detailed",
                    format_preference="lists_and_bullets",
                    code_commenting="debugging_focused",
                    include_examples=True,
                    include_alternatives=True,
                    personalization_level="standard"
                ),
                capabilities=[
                    AgentCapability.DEBUGGING,
                    AgentCapability.CODE_ANALYSIS,
                    AgentCapability.TESTING,
                    AgentCapability.PERFORMANCE_OPTIMIZATION,
                    AgentCapability.SECURITY_REVIEW
                ]
            )
        }

    async def get_agent_config(self, config_id: str) -> Optional[AgentConfig]:
        """Get agent configuration by ID"""
        return await self.db.get_agent_config(config_id)

    async def get_preset_config(self, personality: AgentPersonality) -> AgentConfig:
        """Get preset configuration for personality type"""
        preset = self.presets.get(personality)
        if not preset:
            # Fallback to helpful personality
            preset = self.presets[AgentPersonality.HELPFUL]
        
        logger.info("Retrieved agent preset", personality=personality)
        return preset

    async def create_agent_config(self, org_id: str, config: AgentConfigCreate, 
                                created_by: str) -> AgentConfig:
        """Create new agent configuration"""
        
        # If using a preset personality, start with preset and apply overrides
        if config.personality_type != AgentPersonality.CUSTOM:
            preset = await self.get_preset_config(config.personality_type)
            
            # Merge preset with custom configuration
            config_dict = preset.dict()
            config_dict.update({
                k: v for k, v in config.dict().items() 
                if v is not None and k != 'id'
            })
            
            # Create new AgentConfig with merged data
            merged_config = AgentConfigCreate(**{
                k: v for k, v in config_dict.items() 
                if k in AgentConfigCreate.__fields__
            })
        else:
            merged_config = config

        agent_config = await self.db.create_agent_config(merged_config, org_id, created_by)
        
        logger.info(
            "Agent configuration created",
            config_id=agent_config.id,
            personality=agent_config.personality_type,
            organization_id=org_id
        )
        
        return agent_config

    async def update_agent_config(self, config_id: str, updates: AgentConfigUpdate,
                                updated_by: str) -> Optional[AgentConfig]:
        """Update existing agent configuration"""
        existing_config = await self.get_agent_config(config_id)
        if not existing_config:
            return None

        # Apply updates
        update_data = {k: v for k, v in updates.dict().items() if v is not None}
        update_data['updated_by'] = updated_by
        update_data['updated_at'] = datetime.utcnow()

        # Update in database
        if self.db.pool:
            async with self.db.get_connection() as conn:
                # Build dynamic update query
                set_clauses = []
                params = []
                param_count = 1
                
                for field, value in update_data.items():
                    if field in ['name', 'description', 'system_prompt', 'is_active']:
                        set_clauses.append(f"{field} = ${param_count}")
                        params.append(value)
                        param_count += 1
                    elif field == 'response_style' and isinstance(value, ResponseStyle):
                        set_clauses.append(f"response_style = ${param_count}")
                        params.append(json.dumps(value.dict()))
                        param_count += 1
                    elif field == 'capabilities' and isinstance(value, list):
                        set_clauses.append(f"capabilities = ${param_count}")
                        params.append([c.value if hasattr(c, 'value') else c for c in value])
                        param_count += 1
                    elif field in ['settings'] and isinstance(value, dict):
                        set_clauses.append(f"{field} = ${param_count}")
                        params.append(json.dumps(value))
                        param_count += 1
                    elif field in ['updated_by', 'updated_at']:
                        set_clauses.append(f"{field} = ${param_count}")
                        params.append(value)
                        param_count += 1

                if set_clauses:
                    query = f"""
                        UPDATE agent_configs 
                        SET {', '.join(set_clauses)}
                        WHERE id = ${param_count}
                    """
                    params.append(config_id)
                    await conn.execute(query, *params)
        else:
            # Memory storage update
            if config_id in self.db._memory_storage['agent_configs']:
                stored_config = self.db._memory_storage['agent_configs'][config_id]
                stored_config.update(update_data)

        # Clear context cache for this config
        self._clear_context_cache(config_id)

        updated_config = await self.get_agent_config(config_id)
        
        logger.info(
            "Agent configuration updated",
            config_id=config_id,
            updated_by=updated_by,
            changes=list(update_data.keys())
        )
        
        return updated_config

    async def list_agent_configs(self, org_id: str, include_presets: bool = False) -> List[AgentConfig]:
        """List agent configurations for organization"""
        configs = await self.db.list_agent_configs(org_id)
        
        if include_presets:
            # Add preset configurations
            for personality, preset in self.presets.items():
                preset_copy = preset.copy()
                preset_copy.organization_id = org_id
                preset_copy.name = f"{preset.name} (Preset)"
                preset_copy.id = f"preset_{personality.value}"
                configs.append(preset_copy)
        
        return configs

    async def get_default_agent_config(self, org_id: str) -> Optional[AgentConfig]:
        """Get default agent configuration for organization"""
        configs = await self.list_agent_configs(org_id)
        
        # Find marked default
        for config in configs:
            if config.is_default:
                return config
        
        # If no default marked, return helpful preset
        if configs:
            return configs[0]
        
        # Fallback to helpful preset
        preset = await self.get_preset_config(AgentPersonality.HELPFUL)
        preset.organization_id = org_id
        return preset

    async def get_agent_for_repository(self, repository: Repository) -> AgentConfig:
        """Get appropriate agent configuration for repository"""
        if repository.agent_config_id:
            config = await self.get_agent_config(repository.agent_config_id)
            if config:
                return config
        
        # Fall back to organization default
        default_config = await self.get_default_agent_config(repository.organization_id)
        if default_config:
            return default_config
        
        # Final fallback to helpful preset
        preset = await self.get_preset_config(AgentPersonality.HELPFUL)
        preset.organization_id = repository.organization_id
        return preset

    async def load_agent_context(self, agent_config: AgentConfig, repository: Repository,
                               task_type: str) -> Dict[str, Any]:
        """Load agent-specific context for task processing"""
        cache_key = f"{agent_config.id}:{repository.id}:{task_type}"
        
        if cache_key in self._context_cache:
            logger.debug("Context cache hit", cache_key=cache_key)
            return self._context_cache[cache_key]

        context = {
            "agent_personality": agent_config.personality_type.value,
            "response_style": agent_config.response_style.dict(),
            "capabilities": [c.value for c in agent_config.capabilities],
            "repository_info": {
                "name": repository.full_name,
                "description": repository.description,
                "settings": repository.settings
            },
            "task_type": task_type,
            "context_files": await self._load_context_files(agent_config, repository),
            "system_prompt": agent_config.system_prompt,
            "max_context_length": agent_config.max_context_length,
            "timeout_seconds": agent_config.timeout_seconds
        }

        # Add personality-specific context
        context.update(await self._get_personality_context(agent_config.personality_type, task_type))

        # Cache the context
        self._context_cache[cache_key] = context
        
        logger.info(
            "Agent context loaded",
            agent_id=agent_config.id,
            repository=repository.full_name,
            task_type=task_type,
            context_files_count=len(context["context_files"])
        )
        
        return context

    async def build_system_prompt(self, agent_config: AgentConfig, context: Dict[str, Any]) -> str:
        """Build complete system prompt with context injection"""
        base_prompt = agent_config.system_prompt
        
        # Add context-specific instructions
        repository_info = context.get("repository_info", {})
        context_additions = []
        
        if repository_info.get("name"):
            context_additions.append(f"Repository: {repository_info['name']}")
        
        if repository_info.get("description"):
            context_additions.append(f"Description: {repository_info['description']}")
        
        if context.get("task_type"):
            context_additions.append(f"Task Type: {context['task_type']}")
        
        # Add capability-specific instructions
        capabilities = context.get("capabilities", [])
        if capabilities:
            capability_instructions = self._get_capability_instructions(capabilities)
            if capability_instructions:
                context_additions.append(f"Available Capabilities: {', '.join(capability_instructions)}")
        
        # Add response style guidance
        response_style = context.get("response_style", {})
        style_instructions = self._get_style_instructions(response_style)
        if style_instructions:
            context_additions.append(f"Response Style: {style_instructions}")
        
        # Combine prompt with context
        if context_additions:
            enhanced_prompt = f"{base_prompt}\n\nContext:\n" + "\n".join(f"- {addition}" for addition in context_additions)
        else:
            enhanced_prompt = base_prompt
        
        return enhanced_prompt

    async def _load_context_files(self, agent_config: AgentConfig, repository: Repository) -> List[str]:
        """Load context files based on agent configuration"""
        context_files = []
        
        # Add agent-specific context files
        for file_pattern in agent_config.context_files:
            # Resolve file patterns relative to repository
            if file_pattern.startswith("http"):
                context_files.append(file_pattern)
            else:
                # Local file patterns would be resolved here
                # For now, just add the pattern
                context_files.append(file_pattern)
        
        # Add repository-specific context files
        repo_context_files = repository.settings.get("context_files", [])
        context_files.extend(repo_context_files)
        
        return context_files

    async def _get_personality_context(self, personality: AgentPersonality, task_type: str) -> Dict[str, Any]:
        """Get personality-specific context additions"""
        personality_contexts = {
            AgentPersonality.TECHNICAL: {
                "focus_areas": ["performance", "security", "architecture", "best_practices"],
                "preferred_detail_level": "comprehensive",
                "code_style": "enterprise"
            },
            AgentPersonality.HELPFUL: {
                "focus_areas": ["usability", "clarity", "guidance", "support"],
                "preferred_detail_level": "balanced",
                "code_style": "readable"
            },
            AgentPersonality.CONCISE: {
                "focus_areas": ["efficiency", "brevity", "action"],
                "preferred_detail_level": "minimal",
                "code_style": "compact"
            },
            AgentPersonality.EDUCATIONAL: {
                "focus_areas": ["learning", "understanding", "explanation", "growth"],
                "preferred_detail_level": "comprehensive",
                "code_style": "educational"
            },
            AgentPersonality.DEBUGGING: {
                "focus_areas": ["troubleshooting", "analysis", "systematic_approach", "root_cause"],
                "preferred_detail_level": "detailed",
                "code_style": "diagnostic"
            }
        }
        
        return personality_contexts.get(personality, {})

    def _get_capability_instructions(self, capabilities: List[str]) -> List[str]:
        """Get instructions based on available capabilities"""
        capability_instructions = {
            AgentCapability.CODE_ANALYSIS.value: "Analyze code quality, structure, and improvements",
            AgentCapability.CODE_GENERATION.value: "Generate new code following best practices",
            AgentCapability.DOCUMENTATION.value: "Create comprehensive documentation",
            AgentCapability.TESTING.value: "Design and implement tests",
            AgentCapability.DEBUGGING.value: "Identify and fix bugs systematically",
            AgentCapability.REFACTORING.value: "Improve code structure and maintainability",
            AgentCapability.SECURITY_REVIEW.value: "Identify security vulnerabilities and fixes",
            AgentCapability.PERFORMANCE_OPTIMIZATION.value: "Optimize code for better performance",
            AgentCapability.ARCHITECTURE_REVIEW.value: "Review and improve system architecture",
            AgentCapability.DEPLOYMENT_ASSISTANCE.value: "Help with deployment and infrastructure"
        }
        
        return [capability_instructions[cap] for cap in capabilities if cap in capability_instructions]

    def _get_style_instructions(self, response_style: Dict[str, Any]) -> str:
        """Get style instructions from response style configuration"""
        instructions = []
        
        tone = response_style.get("tone", "professional")
        if tone:
            instructions.append(f"tone: {tone}")
        
        emoji_usage = response_style.get("emoji_usage", "moderate")
        if emoji_usage != "moderate":
            instructions.append(f"emoji usage: {emoji_usage}")
        
        explanation_depth = response_style.get("explanation_depth", "balanced")
        if explanation_depth != "balanced":
            instructions.append(f"explanation depth: {explanation_depth}")
        
        max_length = response_style.get("max_response_length")
        if max_length:
            instructions.append(f"max response length: {max_length} characters")
        
        return ", ".join(instructions)

    def _clear_context_cache(self, config_id: str):
        """Clear context cache for specific agent configuration"""
        keys_to_remove = [key for key in self._context_cache.keys() if key.startswith(f"{config_id}:")]
        for key in keys_to_remove:
            del self._context_cache[key]

    async def get_performance_metrics(self, config_id: str, days: int = 30) -> Dict[str, Any]:
        """Get performance metrics for agent configuration"""
        # This would integrate with the metrics system
        # For now, return placeholder data
        return {
            "config_id": config_id,
            "period_days": days,
            "total_tasks": 0,
            "success_rate": 0.0,
            "average_response_time": 0.0,
            "user_satisfaction": 0.0,
            "most_common_tasks": [],
            "performance_trend": "stable"
        }