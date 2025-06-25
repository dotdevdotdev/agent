"""
Issue-to-prompt conversion system for Claude Code CLI
"""

import re
import structlog
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .issue_parser import ParsedTask, TaskType, TaskPriority
from .git_service import GitService

logger = structlog.get_logger()


class PromptTemplate(str, Enum):
    """Available prompt templates"""
    CODE_ANALYSIS = "code_analysis"
    FEATURE_IMPLEMENTATION = "feature_implementation"
    BUG_INVESTIGATION = "bug_investigation"
    REFACTORING = "refactoring"
    DOCUMENTATION = "documentation"
    GENERAL_ASSISTANCE = "general_assistance"
    TESTING = "testing"


@dataclass
class PromptContext:
    """Context information for prompt building"""
    repository_name: str
    issue_number: int
    job_id: str
    working_directory: str
    file_contents: Dict[str, str] = field(default_factory=dict)
    file_summaries: Dict[str, str] = field(default_factory=dict)
    repository_structure: List[str] = field(default_factory=list)
    recent_commits: List[str] = field(default_factory=list)
    related_issues: List[str] = field(default_factory=list)
    # Worktree recovery context
    worktree_info: Optional[Dict[str, Any]] = None
    is_recovery_job: bool = False
    previous_progress: Optional[Dict[str, Any]] = None


@dataclass
class BuiltPrompt:
    """Result of prompt building process"""
    prompt: str
    template_used: PromptTemplate
    context_files: List[str]
    estimated_tokens: int
    truncated: bool = False
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class PromptBuilderError(Exception):
    """Custom exception for prompt builder errors"""
    def __init__(self, message: str, task: ParsedTask = None):
        self.message = message
        self.task = task
        super().__init__(message)


class PromptBuilder:
    """Converts GitHub issues to optimized Claude Code CLI prompts"""

    def __init__(self, git_service: GitService = None):
        self.git_service = git_service
        self.max_prompt_tokens = 100000  # Conservative limit for Claude
        self.max_file_content_tokens = 50000  # Limit for file contents
        self.avg_chars_per_token = 4  # Rough approximation
        
        # Template definitions
        self.templates = {
            PromptTemplate.CODE_ANALYSIS: self._get_code_analysis_template(),
            PromptTemplate.FEATURE_IMPLEMENTATION: self._get_feature_implementation_template(),
            PromptTemplate.BUG_INVESTIGATION: self._get_bug_investigation_template(),
            PromptTemplate.REFACTORING: self._get_refactoring_template(),
            PromptTemplate.DOCUMENTATION: self._get_documentation_template(),
            PromptTemplate.GENERAL_ASSISTANCE: self._get_general_assistance_template(),
            PromptTemplate.TESTING: self._get_testing_template()
        }
        
        logger.info(
            "Prompt builder initialized",
            templates_loaded=len(self.templates),
            max_prompt_tokens=self.max_prompt_tokens
        )

    async def build_prompt(self, 
                          task: ParsedTask, 
                          context: PromptContext) -> BuiltPrompt:
        """Build optimized prompt for Claude Code CLI"""
        
        try:
            # Select appropriate template
            template = self._select_template(task)
            
            # Gather file contents and context
            enriched_context = await self._enrich_context(task, context)
            
            # Build the prompt using template
            prompt_content = self._apply_template(template, task, enriched_context)
            
            # Optimize and validate prompt
            optimized_prompt = self._optimize_prompt(prompt_content, enriched_context)
            
            # Calculate token estimate
            estimated_tokens = self._estimate_tokens(optimized_prompt.prompt)
            
            result = BuiltPrompt(
                prompt=optimized_prompt.prompt,
                template_used=template,
                context_files=optimized_prompt.context_files,
                estimated_tokens=estimated_tokens,
                truncated=optimized_prompt.truncated,
                warnings=optimized_prompt.warnings,
                metadata={
                    "task_type": task.task_type,
                    "task_priority": task.priority,
                    "repository": context.repository_name,
                    "issue_number": context.issue_number,
                    "files_analyzed": len(enriched_context.file_contents)
                }
            )
            
            logger.info(
                "Prompt built successfully",
                job_id=context.job_id,
                template=template,
                estimated_tokens=estimated_tokens,
                context_files=len(result.context_files),
                truncated=result.truncated
            )
            
            return result
            
        except Exception as e:
            logger.error("Failed to build prompt", job_id=context.job_id, error=str(e))
            raise PromptBuilderError(f"Failed to build prompt: {str(e)}", task)

    def _select_template(self, task: ParsedTask) -> PromptTemplate:
        """Select the most appropriate template for the task"""
        task_type_mapping = {
            TaskType.CODE_ANALYSIS: PromptTemplate.CODE_ANALYSIS,
            TaskType.FEATURE_IMPLEMENTATION: PromptTemplate.FEATURE_IMPLEMENTATION,
            TaskType.BUG_INVESTIGATION: PromptTemplate.BUG_INVESTIGATION,
            TaskType.REFACTORING: PromptTemplate.REFACTORING,
            TaskType.DOCUMENTATION: PromptTemplate.DOCUMENTATION,
            TaskType.CODE_REVIEW: PromptTemplate.CODE_ANALYSIS,
            TaskType.RESEARCH: PromptTemplate.GENERAL_ASSISTANCE,
            TaskType.QUESTION: PromptTemplate.GENERAL_ASSISTANCE
        }
        
        template = task_type_mapping.get(task.task_type, PromptTemplate.GENERAL_ASSISTANCE)
        
        return template

    async def _enrich_context(self, task: ParsedTask, context: PromptContext) -> PromptContext:
        """Enrich context with file contents and repository information"""
        enriched = PromptContext(
            repository_name=context.repository_name,
            issue_number=context.issue_number,
            job_id=context.job_id,
            working_directory=context.working_directory,
            file_contents=context.file_contents.copy(),
            file_summaries=context.file_summaries.copy(),
            repository_structure=context.repository_structure.copy(),
            recent_commits=context.recent_commits.copy(),
            related_issues=context.related_issues.copy()
        )
        
        # Load file contents for referenced files
        if task.relevant_files and self.git_service:
            for file_path in task.relevant_files:
                if file_path not in enriched.file_contents:
                    content = self.git_service.get_file_content(context.job_id, file_path)
                    if content:
                        enriched.file_contents[file_path] = content
                    else:
                        logger.warning("File not found", file_path=file_path, job_id=context.job_id)
        
        # Get repository structure if not provided
        if not enriched.repository_structure and self.git_service:
            enriched.repository_structure = self.git_service.list_files(
                context.job_id, pattern="**/*.{py,js,ts,md,yml,yaml,json,toml}"
            )
        
        return enriched

    def _apply_template(self, 
                       template: PromptTemplate, 
                       task: ParsedTask, 
                       context: PromptContext) -> str:
        """Apply the selected template with task and context data"""
        
        template_content = self.templates[template]
        
        # Common template variables
        template_vars = {
            "repository_name": context.repository_name,
            "issue_number": context.issue_number,
            "task_type": task.task_type.value if task.task_type else "general",
            "task_priority": task.priority.value if task.priority else "medium",
            "prompt": task.prompt,
            "context": task.context or "No additional context provided.",
            "relevant_files": self._format_file_list(task.relevant_files),
            "file_contents": self._format_file_contents(context.file_contents),
            "repository_structure": self._format_repository_structure(context.repository_structure),
            "estimated_complexity": task.estimated_complexity or "Unknown",
            "worktree_context": self._format_worktree_context(context)
        }
        
        # Apply template substitution
        try:
            formatted_prompt = template_content.format(**template_vars)
        except KeyError as e:
            logger.error("Template formatting error", template=template, missing_key=str(e))
            # Fall back to basic template
            formatted_prompt = self._get_basic_template().format(**template_vars)
        
        return formatted_prompt

    def _optimize_prompt(self, prompt: str, context: PromptContext) -> 'OptimizedPrompt':
        """Optimize prompt for token limits and Claude Code CLI effectiveness"""
        
        @dataclass
        class OptimizedPrompt:
            prompt: str
            context_files: List[str]
            truncated: bool = False
            warnings: List[str] = field(default_factory=list)
        
        result = OptimizedPrompt(
            prompt=prompt,
            context_files=list(context.file_contents.keys())
        )
        
        current_tokens = self._estimate_tokens(prompt)
        
        if current_tokens <= self.max_prompt_tokens:
            return result
        
        # Prompt is too long, need to optimize
        result.truncated = True
        result.warnings.append(f"Prompt truncated from ~{current_tokens} to fit token limit")
        
        # Strategy 1: Truncate file contents
        if context.file_contents:
            truncated_contents = {}
            remaining_tokens = self.max_file_content_tokens
            
            # Prioritize files mentioned in relevant_files
            file_priority = list(context.file_contents.keys())
            
            for file_path in file_priority:
                content = context.file_contents[file_path]
                content_tokens = self._estimate_tokens(content)
                
                if content_tokens <= remaining_tokens:
                    truncated_contents[file_path] = content
                    remaining_tokens -= content_tokens
                else:
                    # Truncate this file
                    max_chars = remaining_tokens * self.avg_chars_per_token
                    truncated_content = content[:int(max_chars * 0.8)]  # Leave some buffer
                    truncated_content += "\n\n... [Content truncated for length] ..."
                    truncated_contents[file_path] = truncated_content
                    break
            
            # Rebuild prompt with truncated content
            context.file_contents = truncated_contents
            result.prompt = prompt.replace(
                self._format_file_contents(context.file_contents),
                self._format_file_contents(truncated_contents)
            )
            result.context_files = list(truncated_contents.keys())
        
        # Strategy 2: Remove repository structure if still too long
        current_tokens = self._estimate_tokens(result.prompt)
        if current_tokens > self.max_prompt_tokens:
            result.prompt = result.prompt.replace(
                self._format_repository_structure(context.repository_structure),
                "Repository structure omitted due to length constraints."
            )
            result.warnings.append("Repository structure omitted to fit token limit")
        
        return result

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text"""
        return len(text) // self.avg_chars_per_token

    def _format_file_list(self, files: List[str]) -> str:
        """Format list of files for template"""
        if not files:
            return "No specific files mentioned."
        
        formatted = "Files to focus on:\n"
        for file_path in files:
            formatted += f"- {file_path}\n"
        return formatted

    def _format_file_contents(self, file_contents: Dict[str, str]) -> str:
        """Format file contents for template"""
        if not file_contents:
            return "No file contents loaded."
        
        formatted = "File Contents:\n\n"
        for file_path, content in file_contents.items():
            formatted += f"### {file_path}\n\n"
            formatted += f"```\n{content}\n```\n\n"
        return formatted

    def _format_repository_structure(self, structure: List[str]) -> str:
        """Format repository structure for template"""
        if not structure:
            return "Repository structure not available."
        
        if len(structure) > 50:  # Limit structure size
            structure = structure[:50] + ["... (truncated)"]
        
        formatted = "Repository Structure:\n\n"
        for file_path in structure:
            formatted += f"- {file_path}\n"
        return formatted

    # Template definitions
    def _get_code_analysis_template(self) -> str:
        return """# Code Analysis Request



## Task Details
- **Repository**: {repository_name}
- **Issue**: #{issue_number}
- **Task Type**: {task_type}
- **Priority**: {task_priority}
- **Complexity**: {estimated_complexity}

## Analysis Request
{prompt}

## Additional Context
{context}

## Files to Analyze
{relevant_files}

{file_contents}

## Repository Overview
{repository_structure}

{worktree_context}

## Instructions
Please provide a comprehensive code analysis focusing on:
1. Code quality and best practices
2. Performance considerations
3. Security implications
4. Maintainability and readability
5. Specific issues or improvements identified

If you find issues, please provide specific recommendations with code examples where appropriate."""

    def _get_feature_implementation_template(self) -> str:
        return """# Feature Implementation Request



## Task Details
- **Repository**: {repository_name}
- **Issue**: #{issue_number}
- **Task Type**: {task_type}
- **Priority**: {task_priority}
- **Complexity**: {estimated_complexity}

## Feature Requirements
{prompt}

## Additional Context
{context}

## Relevant Files
{relevant_files}

{file_contents}

## Repository Overview
{repository_structure}

{worktree_context}

## Implementation Guidelines
Please implement the requested feature following these principles:
1. Follow existing code patterns and conventions
2. Include appropriate error handling
3. Add necessary tests
4. Update documentation as needed
5. Consider backwards compatibility
6. Ensure security best practices

Please provide the complete implementation with explanations for key decisions."""

    def _get_bug_investigation_template(self) -> str:
        return """# Bug Investigation Request



## Task Details
- **Repository**: {repository_name}
- **Issue**: #{issue_number}
- **Task Type**: {task_type}
- **Priority**: {task_priority}
- **Complexity**: {estimated_complexity}

## Bug Description
{prompt}

## Additional Context
{context}

## Relevant Files
{relevant_files}

{file_contents}

## Repository Overview
{repository_structure}

{worktree_context}

## Investigation Approach
Please investigate this bug systematically:
1. Analyze the reported symptoms
2. Identify potential root causes
3. Trace through the relevant code paths
4. Reproduce the issue if possible
5. Propose specific fixes
6. Consider edge cases and testing

Please provide a detailed analysis with reproduction steps and recommended fixes."""

    def _get_refactoring_template(self) -> str:
        return """# Code Refactoring Request



## Task Details
- **Repository**: {repository_name}
- **Issue**: #{issue_number}
- **Task Type**: {task_type}
- **Priority**: {task_priority}
- **Complexity**: {estimated_complexity}

## Refactoring Goals
{prompt}

## Additional Context
{context}

## Files to Refactor
{relevant_files}

{file_contents}

## Repository Overview
{repository_structure}

{worktree_context}

## Refactoring Guidelines
Please refactor the code with these objectives:
1. Improve code clarity and readability
2. Enhance maintainability
3. Optimize performance where appropriate
4. Follow design patterns and best practices
5. Maintain existing functionality
6. Preserve backward compatibility

Please provide the refactored code with explanations for the changes made."""

    def _get_documentation_template(self) -> str:
        return """# Documentation Request



## Task Details
- **Repository**: {repository_name}
- **Issue**: #{issue_number}
- **Task Type**: {task_type}
- **Priority**: {task_priority}

## Documentation Requirements
{prompt}

## Additional Context
{context}

## Relevant Files
{relevant_files}

{file_contents}

## Repository Overview
{repository_structure}

{worktree_context}

## Documentation Guidelines
Please create comprehensive documentation that:
1. Clearly explains the purpose and functionality
2. Includes usage examples
3. Documents API interfaces and parameters
4. Provides setup and installation instructions
5. Includes troubleshooting information
6. Follows documentation best practices

Please provide well-structured documentation in appropriate format (Markdown, etc.)."""

    def _get_testing_template(self) -> str:
        return """# Testing Request



## Task Details
- **Repository**: {repository_name}
- **Issue**: #{issue_number}
- **Task Type**: {task_type}
- **Priority**: {task_priority}

## Testing Requirements
{prompt}

## Additional Context
{context}

## Files to Test
{relevant_files}

{file_contents}

## Repository Overview
{repository_structure}

{worktree_context}

## Testing Guidelines
Please create comprehensive tests that:
1. Cover the main functionality and edge cases
2. Include unit tests and integration tests as appropriate
3. Follow testing best practices and conventions
4. Provide good test coverage
5. Include both positive and negative test cases
6. Are maintainable and readable

Please provide well-structured test code with explanations."""

    def _get_general_assistance_template(self) -> str:
        return """# General Assistance Request



## Task Details
- **Repository**: {repository_name}
- **Issue**: #{issue_number}
- **Task Type**: {task_type}
- **Priority**: {task_priority}

## Request
{prompt}

## Additional Context
{context}

## Relevant Files
{relevant_files}

{file_contents}

## Repository Overview
{repository_structure}

{worktree_context}

## Response Guidelines
Please provide helpful assistance that:
1. Directly addresses the question or request
2. Provides clear and actionable information
3. Includes examples where appropriate
4. Considers the context of the repository
5. Offers best practices and recommendations

Please provide a comprehensive and helpful response."""

    def _get_basic_template(self) -> str:
        return """# Request

## Task
{prompt}

## Context
{context}

## Files
{relevant_files}

{file_contents}

Please provide assistance with this request."""

    def _format_worktree_context(self, context: PromptContext) -> str:
        """Format worktree context information for templates"""
        if not context.worktree_info and not context.is_recovery_job:
            return ""
        
        sections = []
        
        if context.is_recovery_job:
            sections.append("## ⚠️ RECOVERY JOB CONTEXT")
            sections.append("This is a **recovery job** - you are resuming work from a previous interrupted session.")
            
            if context.worktree_info:
                worktree = context.worktree_info
                sections.append(f"**Previous worktree details:**")
                sections.append(f"- Branch: `{worktree.get('branch_name', 'unknown')}`")
                sections.append(f"- Worktree path: `{worktree.get('worktree_path', 'unknown')}`")
                sections.append(f"- Status when interrupted: `{worktree.get('status', 'unknown')}`")
                
                if worktree.get('files_modified'):
                    sections.append(f"- Files previously modified: {', '.join(worktree['files_modified'])}")
                if worktree.get('files_created'):
                    sections.append(f"- Files previously created: {', '.join(worktree['files_created'])}")
                if worktree.get('commits_made'):
                    sections.append(f"- Commits made: {len(worktree['commits_made'])} commits")
            
            if context.previous_progress:
                progress = context.previous_progress
                sections.append(f"**Previous progress:**")
                sections.append(f"- Last stage: {progress.get('stage', 'unknown')}")
                sections.append(f"- Progress: {progress.get('progress', 0)}%")
                if progress.get('message'):
                    sections.append(f"- Last message: {progress['message']}")
            
            sections.append("")
            sections.append("**Recovery Instructions:**")
            sections.append("1. **Check existing work** - Review any previous changes in the worktree")
            sections.append("2. **Continue from where left off** - Don't start over, build on existing progress")
            sections.append("3. **Validate previous work** - Ensure previous changes are correct before proceeding")
            sections.append("4. **Complete the task** - Finish what was started in the previous session")
            sections.append("")
        
        # Add general worktree awareness instructions
        sections.append("## 🔧 WORKTREE ENVIRONMENT")
        sections.append("You are working in an **isolated git worktree** for this issue:")
        sections.append("- This is a separate working directory from the main repository")
        sections.append("- Changes made here won't affect the main branch until explicitly merged")
        sections.append("- The worktree will be cleaned up automatically after task completion")
        sections.append("- You can freely create, modify, and delete files as needed")
        sections.append("")
        
        return "\n".join(sections)

    def build_simple_question_prompt(self, context: 'PromptContext', task: ParsedTask) -> 'BuiltPrompt':
        """Build a simple prompt for general questions without file context"""
        
        # Simple template for general questions
        template = """# General Question

## Question
{prompt}

## Additional Context
{context}

Please provide a helpful and comprehensive answer to this question. 
Focus on clarity, accuracy, and practical guidance.
"""
        
        # Build the prompt using task data
        formatted_prompt = template.format(
            prompt=task.prompt,
            context=task.context if task.context else "No additional context provided."
        )
        
        return BuiltPrompt(
            prompt=formatted_prompt,
            template_used=PromptTemplate.GENERAL_ASSISTANCE,
            context_files=[],
            estimated_tokens=len(formatted_prompt.split()) * 1.3,  # Rough estimate
            truncated=False,
            metadata={
                "is_simple_question": True,
                "no_files_included": True
            }
        )