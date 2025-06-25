# Agent Configurations

This directory contains JSON configuration files that define different AI agent behaviors for processing GitHub issues.

## How It Works

- Each `.json` file defines a complete agent configuration
- The system automatically loads all active agent configs from this directory
- The `default.json` agent is used when no specific agent is requested
- Users can create custom agents by copying and modifying existing configs

## Agent Configuration Format

```json
{
  "name": "Agent Name",
  "description": "Brief description of what this agent does",
  "system_prompt": "The core instructions that define the agent's behavior and personality",
  "response_style": {
    "tone": "helpful_and_professional",
    "emoji_usage": "moderate",
    "explanation_depth": "balanced",
    "include_code_examples": true,
    "max_response_length": null
  },
  "capabilities": [
    "code_analysis",
    "bug_fixing",
    "documentation"
  ],
  "context_files": [
    "README.md",
    "docs/"
  ],
  "timeout_seconds": 3600,
  "is_active": true
}
```

## Available Agents

- **default.json** - The original helpful assistant (recommended starting point)
- **technical-expert.json** - Detailed technical analysis and best practices
- **concise-helper.json** - Quick, direct responses with minimal explanation
- **debugging-specialist.json** - Systematic debugging and troubleshooting

## Creating Custom Agents

1. Copy an existing agent config that's closest to what you want
2. Modify the `name`, `description`, and `system_prompt` fields
3. Adjust `response_style` and `capabilities` as needed
4. Save with a descriptive filename (e.g., `my-custom-agent.json`)
5. Set `is_active: true` to enable the agent

## Response Style Options

- **tone**: `helpful_and_professional`, `direct_and_efficient`, `systematic_and_analytical`, etc.
- **emoji_usage**: `none`, `minimal`, `moderate`, `extensive`
- **explanation_depth**: `minimal`, `balanced`, `detailed`, `comprehensive`
- **max_response_length**: `null` for no limit, or number of characters

## Common Capabilities

- `code_analysis` - Analyze code quality and structure
- `bug_fixing` - Identify and fix bugs
- `documentation` - Create or improve documentation
- `testing_strategies` - Suggest testing approaches
- `architecture_review` - Review system design
- `performance_optimization` - Improve performance
- `security_review` - Identify security issues
- `debugging` - Systematic troubleshooting
- `code_generation` - Create new code