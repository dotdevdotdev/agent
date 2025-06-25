"""
Intelligent GitHub issue parser for agent task extraction
"""

import re
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
import structlog
from src.models.configuration import AgentManager

logger = structlog.get_logger()


class TaskType(str, Enum):
    CODE_ANALYSIS = "Code Analysis"
    DOCUMENTATION = "Documentation Generation"
    REFACTORING = "Code Refactoring"
    RESEARCH = "Research and Summarization"
    QUESTION = "General Question"
    BUG_INVESTIGATION = "Bug Investigation"
    FEATURE_IMPLEMENTATION = "Feature Implementation"
    CODE_REVIEW = "Code Review"


class TaskPriority(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class OutputFormat(str, Enum):
    CODE_CHANGES = "Code changes with explanations"
    ANALYSIS_REPORT = "Analysis report"
    DOCUMENTATION = "Documentation updates"
    IMPLEMENTATION_PLAN = "Implementation plan"
    BUG_FIX = "Bug fix with tests"
    GENERAL_RESPONSE = "General response"


@dataclass
class ParsedTask:
    task_type: TaskType
    priority: TaskPriority
    prompt: str
    relevant_files: List[str]
    context: str
    output_format: OutputFormat
    estimated_complexity: str
    validation_errors: List[str]
    raw_issue_body: str
    agent_id: str = "default"  # Which agent to use for this task
    acknowledgements_confirmed: bool = False
    issue_author: str = ""  # GitHub username who created the issue


class IssueParser:
    """Intelligent parser for GitHub issue templates"""

    def __init__(self):
        # Initialize agent manager for dynamic agent discovery
        self.agent_manager = AgentManager()
        
        # Regex patterns for parsing GitHub issue template fields
        self.field_patterns = {
            'agent': r'### Agent Selection\s*\n\s*(.+?)(?=\n###|\n\n|\Z)',
            'task-type': r'### Task Type\s*\n\s*(.+?)(?=\n###|\n\n|\Z)',
            'priority': r'### Priority Level\s*\n\s*(.+?)(?=\n###|\n\n|\Z)',
            'prompt': r'### Detailed Prompt\s*\n\s*(.*?)(?=\n###|\n\n(?=[A-Z])|\Z)',
            'relevant-files': r'### Relevant Files or URLs\s*\n\s*(.+?)(?=\n###|\n\n|\Z)',
            'context': r'### Additional Context\s*\n\s*(.*?)(?=\n###|\n\n(?=[A-Z])|\Z)',
            'output-format': r'### Preferred Output Format\s*\n\s*(.+?)(?=\n###|\n\n|\Z)',
            'acknowledgements': r'### Acknowledgements\s*\n(.*?)(?=\n###|\Z)'
        }

        # Legacy mapping for backward compatibility (will be enhanced with fuzzy matching)
        self.legacy_agent_mapping = {
            'Default Assistant (Recommended)': 'default',
            'Technical Expert (Detailed technical analysis)': 'technical-expert',
            'Concise Helper (Quick, direct responses)': 'concise-helper', 
            'Debugging Specialist (Systematic troubleshooting)': 'debugging-specialist'
        }

    def parse_issue(self, issue_body: str, issue_title: str, issue_author: str = "") -> ParsedTask:
        """Parse GitHub issue body and extract structured task data"""
        logger.info("Parsing GitHub issue", title=issue_title[:50])

        validation_errors = []
        
        # Extract fields from issue body
        agent_str = self._extract_field_value(issue_body, 'agent')
        task_type_str = self._extract_field_value(issue_body, 'task-type')
        priority_str = self._extract_field_value(issue_body, 'priority')
        prompt = self._extract_field_value(issue_body, 'prompt')
        files_text = self._extract_field_value(issue_body, 'relevant-files') or ""
        context = self._extract_field_value(issue_body, 'context') or ""
        output_format_str = self._extract_field_value(issue_body, 'output-format')
        acknowledgements_text = self._extract_field_value(issue_body, 'acknowledgements') or ""

        # Resolve agent selection with fuzzy matching
        agent_id = self._resolve_agent_id(agent_str)
        if agent_str and agent_id == "default" and not self._exact_match(agent_str):
            validation_errors.append(f"Agent '{agent_str}' not found, using default")

        # Convert strings to enums with validation
        try:
            task_type = TaskType(task_type_str) if task_type_str else TaskType.QUESTION
        except ValueError:
            validation_errors.append(f"Invalid task type: {task_type_str}")
            task_type = TaskType.QUESTION

        try:
            priority = TaskPriority(priority_str) if priority_str else TaskPriority.MEDIUM
        except ValueError:
            validation_errors.append(f"Invalid priority: {priority_str}")
            priority = TaskPriority.MEDIUM

        try:
            output_format = OutputFormat(output_format_str) if output_format_str else OutputFormat.ANALYSIS_REPORT
        except ValueError:
            validation_errors.append(f"Invalid output format: {output_format_str}")
            output_format = OutputFormat.ANALYSIS_REPORT

        # Parse file references
        relevant_files = self._parse_file_references(files_text)

        # Check acknowledgements
        acknowledgements_confirmed = self._check_acknowledgements(acknowledgements_text)
        # Validate required fields
        if not prompt or prompt.strip() == "":
            validation_errors.append("Detailed prompt is required")
            prompt = f"Please analyze: {issue_title}"

        # Create parsed task
        parsed_task = ParsedTask(
            task_type=task_type,
            priority=priority,
            prompt=prompt.strip() if prompt else "",
            relevant_files=relevant_files,
            context=context.strip() if context else "",
            output_format=output_format,
            estimated_complexity="",  # Will be filled by _estimate_complexity
            validation_errors=validation_errors,
            raw_issue_body=issue_body,
            agent_id=agent_id,
            acknowledgements_confirmed=acknowledgements_confirmed,
            issue_author=issue_author
        )

        # Estimate complexity
        parsed_task.estimated_complexity = self._estimate_complexity(parsed_task)

        # Final validation
        additional_errors = self._validate_task(parsed_task)
        parsed_task.validation_errors.extend(additional_errors)

        logger.info(
            "Issue parsing completed",
            task_type=parsed_task.task_type,
            priority=parsed_task.priority,
            agent_id=parsed_task.agent_id,
            complexity=parsed_task.estimated_complexity,
            errors_count=len(parsed_task.validation_errors)
        )

        return parsed_task

    def _extract_field_value(self, body: str, field_name: str) -> Optional[str]:
        """Extract value for a specific field from issue body"""
        pattern = self.field_patterns.get(field_name)
        if not pattern:
            return None

        match = re.search(pattern, body, re.DOTALL | re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            # Clean up common artifacts
            value = re.sub(r'^\s*[-*]\s*', '', value, flags=re.MULTILINE)  # Remove bullet points
            value = re.sub(r'\n\s*\n', '\n', value)  # Remove extra newlines
            return value if value else None
        return None

    def _parse_file_references(self, files_text: str) -> List[str]:
        """Parse and validate file references from text"""
        if not files_text:
            return []

        # Split by comma and clean up
        files = [f.strip() for f in files_text.split(',')]
        
        # Filter out empty strings and validate basic format
        valid_files = []
        for file_ref in files:
            if file_ref and (
                file_ref.startswith('src/') or 
                file_ref.startswith('docs/') or
                file_ref.startswith('tests/') or
                file_ref.startswith('http') or
                '.' in file_ref  # Has file extension
            ):
                valid_files.append(file_ref)

        return valid_files

    def _check_acknowledgements(self, acknowledgements_text: str) -> bool:
        """Check if required acknowledgements are confirmed"""
        if not acknowledgements_text:
            return False
        
        # Look for checked boxes [x] or confirmation text
        return (
            '[x]' in acknowledgements_text.lower() or
            'yes' in acknowledgements_text.lower() or
            'confirmed' in acknowledgements_text.lower()
        )

    def _estimate_complexity(self, task: ParsedTask) -> str:
        """Analyze task and estimate complexity (Simple/Medium/Complex)"""
        complexity_score = 0

        # Task type complexity weights
        complex_types = [TaskType.FEATURE_IMPLEMENTATION, TaskType.REFACTORING, TaskType.BUG_INVESTIGATION]
        medium_types = [TaskType.CODE_ANALYSIS, TaskType.CODE_REVIEW]
        
        if task.task_type in complex_types:
            complexity_score += 3
        elif task.task_type in medium_types:
            complexity_score += 2
        else:
            complexity_score += 1

        # Prompt length and detail
        if len(task.prompt) > 500:
            complexity_score += 2
        elif len(task.prompt) > 200:
            complexity_score += 1

        # Number of files
        if len(task.relevant_files) > 5:
            complexity_score += 2
        elif len(task.relevant_files) > 1:
            complexity_score += 1

        # Context complexity
        if task.context and len(task.context) > 200:
            complexity_score += 1

        # Priority impact
        if task.priority == TaskPriority.CRITICAL:
            complexity_score += 1

        # Determine final complexity
        if complexity_score >= 6:
            return "Complex"
        elif complexity_score >= 3:
            return "Medium"
        else:
            return "Simple"

    def _validate_task(self, task: ParsedTask) -> List[str]:
        """Validate parsed task and return list of validation errors"""
        errors = []

        # Check for minimum prompt length
        if len(task.prompt) < 10:
            errors.append("Prompt is too short - please provide more detail")

        # Check acknowledgements for certain task types
        if not task.acknowledgements_confirmed:
            errors.append("Please confirm the acknowledgements in the issue form")

        # Validate file references if provided
        for file_ref in task.relevant_files:
            if file_ref.startswith('http') and 'github.com' not in file_ref:
                errors.append(f"External URL not supported: {file_ref}")

        # Check for potential security concerns
        security_keywords = ['password', 'secret', 'key', 'token', 'credential']
        prompt_lower = task.prompt.lower()
        if any(keyword in prompt_lower for keyword in security_keywords):
            errors.append("Please avoid including sensitive information like passwords or secrets")

        return errors

    def is_agent_issue(self, issue_body: str, issue_labels: List[str]) -> bool:
        """Check if this issue is intended for agent processing"""
        # Check for agent labels
        agent_labels = [label for label in issue_labels if label.startswith('agent:')]
        if agent_labels:
            return True

        # Check if it follows the issue template structure
        return any(pattern in issue_body for pattern in ['### Task Type', '### Detailed Prompt'])

    def extract_quick_task(self, issue_title: str, issue_body: str) -> Optional[ParsedTask]:
        """Extract a quick task from non-template issues that might still be agent tasks"""
        # For issues that don't use the template but might be quick agent tasks
        if not issue_body or len(issue_body.strip()) < 20:
            return None

        # Create a minimal parsed task
        return ParsedTask(
            task_type=TaskType.QUESTION,
            priority=TaskPriority.LOW,
            prompt=f"Title: {issue_title}\n\nDescription: {issue_body}",
            relevant_files=[],
            context="Quick task extracted from non-template issue",
            output_format=OutputFormat.ANALYSIS_REPORT,
            estimated_complexity="Simple",
            validation_errors=["Non-template issue - results may be limited"],
            raw_issue_body=issue_body,
            agent_id="default",  # Use default agent for non-template issues
            acknowledgements_confirmed=False
        )

    def _resolve_agent_id(self, agent_str: str) -> str:
        """Resolve agent selection to actual agent ID with fuzzy matching"""
        if not agent_str:
            return "default"
        
        # Get available agents from filesystem
        available_agents = self.agent_manager.load_all_agents()
        
        # 1. Exact legacy mapping first (backward compatibility)
        if agent_str in self.legacy_agent_mapping:
            agent_id = self.legacy_agent_mapping[agent_str]
            if agent_id in available_agents:
                logger.debug("Agent resolved via legacy mapping", 
                           input=agent_str, resolved=agent_id)
                return agent_id
        
        # 2. Exact agent ID match
        if agent_str in available_agents:
            logger.debug("Agent resolved via exact ID match", 
                       input=agent_str, resolved=agent_str)
            return agent_str
        
        # 3. Fuzzy matching against agent names
        for agent_id, agent_config in available_agents.items():
            if self._fuzzy_match(agent_str, agent_config.name):
                logger.debug("Agent resolved via name fuzzy match", 
                           input=agent_str, resolved=agent_id, name=agent_config.name)
                return agent_id
        
        # 4. Fuzzy matching against agent IDs
        for agent_id in available_agents.keys():
            if self._fuzzy_match(agent_str, agent_id):
                logger.debug("Agent resolved via ID fuzzy match", 
                           input=agent_str, resolved=agent_id)
                return agent_id
        
        # 5. Try partial matching for common words
        agent_str_lower = agent_str.lower()
        for agent_id, agent_config in available_agents.items():
            # Check if key words from input are in agent name or description
            if any(word in agent_config.name.lower() for word in agent_str_lower.split() if len(word) > 3):
                logger.debug("Agent resolved via partial word match", 
                           input=agent_str, resolved=agent_id, name=agent_config.name)
                return agent_id
        
        # 6. Ultimate fallback
        logger.info("Agent not found, using default", 
                   input=agent_str, available=list(available_agents.keys()))
        return "default"

    def _fuzzy_match(self, user_input: str, target: str) -> bool:
        """Simple fuzzy matching logic"""
        if not user_input or not target:
            return False
            
        user_lower = user_input.lower().strip()
        target_lower = target.lower().strip()
        
        # Exact match
        if user_lower == target_lower:
            return True
        
        # Substring matching (both directions)
        if user_lower in target_lower or target_lower in user_lower:
            return True
            
        # Handle common transformations
        user_normalized = user_lower.replace(" ", "-").replace("_", "-")
        target_normalized = target_lower.replace(" ", "-").replace("_", "-")
        
        if user_normalized == target_normalized:
            return True
            
        # Check if user input is contained in normalized target
        if user_normalized in target_normalized or target_normalized in user_normalized:
            return True
        
        # Handle common abbreviations/keywords
        keywords = {
            'debug': ['debugging', 'debug'],
            'tech': ['technical', 'expert'],
            'quick': ['concise', 'brief'],
            'help': ['helpful', 'assistant'],
            'short': ['concise', 'brief'],
            'detailed': ['technical', 'expert', 'comprehensive'],
            'simple': ['concise', 'helper']
        }
        
        for keyword, matches in keywords.items():
            if keyword in user_lower and any(match in target_lower for match in matches):
                return True
                
        return False

    def _exact_match(self, agent_str: str) -> bool:
        """Check if the agent string is an exact match for legacy options"""
        return agent_str in self.legacy_agent_mapping