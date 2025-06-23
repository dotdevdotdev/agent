"""
Intelligent GitHub issue parser for agent task extraction
"""

import re
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
import structlog

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
    acknowledgements_confirmed: bool = False
    testing_mode: bool = False  # Allow lower validation scores for testing


class IssueParser:
    """Intelligent parser for GitHub issue templates"""

    def __init__(self):
        # Regex patterns for parsing GitHub issue template fields
        self.field_patterns = {
            'task-type': r'### Task Type\s*\n\s*(.+?)(?=\n###|\n\n|\Z)',
            'priority': r'### Priority Level\s*\n\s*(.+?)(?=\n###|\n\n|\Z)',
            'prompt': r'### Detailed Prompt\s*\n\s*(.*?)(?=\n###|\n\n(?=[A-Z])|\Z)',
            'relevant-files': r'### Relevant Files or URLs\s*\n\s*(.+?)(?=\n###|\n\n|\Z)',
            'context': r'### Additional Context\s*\n\s*(.*?)(?=\n###|\n\n(?=[A-Z])|\Z)',
            'output-format': r'### Preferred Output Format\s*\n\s*(.+?)(?=\n###|\n\n|\Z)',
            'acknowledgements': r'### Acknowledgements\s*\n(.*?)(?=\n###|\Z)'
        }

    def parse_issue(self, issue_body: str, issue_title: str) -> ParsedTask:
        """Parse GitHub issue body and extract structured task data"""
        logger.info("Parsing GitHub issue", title=issue_title[:50])

        validation_errors = []
        
        # Extract fields from issue body
        task_type_str = self._extract_field_value(issue_body, 'task-type')
        priority_str = self._extract_field_value(issue_body, 'priority')
        prompt = self._extract_field_value(issue_body, 'prompt')
        files_text = self._extract_field_value(issue_body, 'relevant-files') or ""
        context = self._extract_field_value(issue_body, 'context') or ""
        output_format_str = self._extract_field_value(issue_body, 'output-format')
        acknowledgements_text = self._extract_field_value(issue_body, 'acknowledgements') or ""

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
        
        # Check for testing mode flag
        testing_mode = self._check_testing_mode(issue_body, issue_title)

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
            acknowledgements_confirmed=acknowledgements_confirmed,
            testing_mode=testing_mode
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

    def _check_testing_mode(self, issue_body: str, issue_title: str) -> bool:
        """Check if testing mode is enabled for this issue"""
        # Check for testing flags in issue body or title
        testing_indicators = [
            '[test]',
            '[testing]', 
            '[dev]',
            '[development]',
            'testing mode',
            'test mode',
            'allow low validation',
            'skip validation'
        ]
        
        combined_text = (issue_body + " " + issue_title).lower()
        
        return any(indicator in combined_text for indicator in testing_indicators)

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

        # Check for testing mode
        testing_mode = self._check_testing_mode(issue_body, issue_title)

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
            acknowledgements_confirmed=False,
            testing_mode=testing_mode
        )