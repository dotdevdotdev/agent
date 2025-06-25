"""
Simple file-based agent configuration models
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from pathlib import Path
import json


class ResponseStyle(BaseModel):
    """Agent response style configuration"""
    tone: str = "helpful_and_professional"
    emoji_usage: str = "moderate"  # none, minimal, moderate, extensive
    explanation_depth: str = "balanced"  # minimal, balanced, detailed, comprehensive
    include_code_examples: bool = True
    max_response_length: Optional[int] = None


class AgentConfig(BaseModel):
    """Simple agent configuration loaded from JSON files"""
    name: str
    description: str
    system_prompt: str
    response_style: ResponseStyle = Field(default_factory=ResponseStyle)
    capabilities: List[str] = Field(default_factory=list)
    context_files: List[str] = Field(default_factory=list)
    timeout_seconds: int = 3600
    is_active: bool = True
    
    # Internal fields (not in JSON)
    config_file: Optional[str] = None
    
    @classmethod
    def load_from_file(cls, file_path: Path) -> "AgentConfig":
        """Load agent configuration from JSON file"""
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        # Parse response_style if it exists
        if 'response_style' in data:
            data['response_style'] = ResponseStyle(**data['response_style'])
        
        config = cls(**data)
        config.config_file = str(file_path)
        return config
    
    def save_to_file(self, file_path: Path) -> None:
        """Save agent configuration to JSON file"""
        data = self.dict(exclude={'config_file'})
        # Convert response_style to dict for JSON serialization
        if isinstance(data['response_style'], ResponseStyle):
            data['response_style'] = data['response_style'].dict()
        
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)


class AgentManager:
    """Manages file-based agent configurations"""
    
    def __init__(self, agents_dir: Path = None):
        self.agents_dir = agents_dir or Path("agents")
        self._agents_cache: Dict[str, AgentConfig] = {}
        self._default_agent: Optional[AgentConfig] = None
    
    def load_all_agents(self) -> Dict[str, AgentConfig]:
        """Load all agent configurations from the agents directory"""
        if not self.agents_dir.exists():
            return {}
        
        agents = {}
        for config_file in self.agents_dir.glob("*.json"):
            try:
                agent = AgentConfig.load_from_file(config_file)
                if agent.is_active:
                    # Use filename (without extension) as the agent ID
                    agent_id = config_file.stem
                    agents[agent_id] = agent
            except Exception as e:
                print(f"Warning: Failed to load agent config {config_file}: {e}")
        
        self._agents_cache = agents
        return agents
    
    def get_agent(self, agent_id: str) -> Optional[AgentConfig]:
        """Get a specific agent configuration"""
        if not self._agents_cache:
            self.load_all_agents()
        return self._agents_cache.get(agent_id)
    
    def get_default_agent(self) -> AgentConfig:
        """Get the default agent configuration"""
        if self._default_agent:
            return self._default_agent
        
        # Try to load 'default' agent first
        default_agent = self.get_agent('default')
        if default_agent:
            self._default_agent = default_agent
            return default_agent
        
        # Fall back to first available agent
        agents = self.load_all_agents()
        if agents:
            first_agent = next(iter(agents.values()))
            self._default_agent = first_agent
            return first_agent
        
        # Create a minimal fallback agent if no configs exist
        fallback = AgentConfig(
            name="Fallback Assistant",
            description="Basic AI assistant when no configurations are available",
            system_prompt="You are a helpful AI assistant focused on analyzing GitHub issues and providing clear solutions.",
            capabilities=["code_analysis", "bug_fixing"]
        )
        self._default_agent = fallback
        return fallback
    
    def list_agents(self) -> List[str]:
        """List all available agent IDs"""
        if not self._agents_cache:
            self.load_all_agents()
        return list(self._agents_cache.keys())
    
    def reload_agents(self) -> None:
        """Reload all agent configurations from disk"""
        self._agents_cache.clear()
        self._default_agent = None
        self.load_all_agents()


# Global agent manager instance
agent_manager = AgentManager()