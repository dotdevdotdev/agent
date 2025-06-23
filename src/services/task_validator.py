"""
Task validation and requirement analysis
"""

import re
import structlog
from typing import Dict, List, Any, Optional
from pathlib import Path

from .issue_parser import ParsedTask, TaskType, TaskPriority

logger = structlog.get_logger()


class TaskValidator:
    """Validates parsed tasks and provides improvement suggestions"""

    def __init__(self):
        self.common_file_patterns = [
            r'.*\.py$',  # Python files
            r'.*\.js$',  # JavaScript files
            r'.*\.ts$',  # TypeScript files
            r'.*\.md$',  # Markdown files
            r'.*\.yml?$',  # YAML files
            r'.*\.json$',  # JSON files
            r'.*\.toml$',  # TOML files
            r'.*\.txt$',  # Text files
        ]

        self.security_patterns = [
            r'password',
            r'secret',
            r'api[_-]?key',
            r'token',
            r'credential',
            r'private[_-]?key',
            r'access[_-]?key',
        ]

    def validate_task_completeness(self, task: ParsedTask) -> Dict[str, Any]:
        """Check if task has sufficient information for processing"""
        logger.info("Validating task completeness", task_type=task.task_type)

        validation_result = {
            'is_valid': True,
            'has_errors': False,
            'errors': [],
            'warnings': [],
            'suggestions': [],
            'completeness_score': 0,
            'feedback': ""
        }

        # Check prompt quality
        prompt_score = self._evaluate_prompt_quality(task.prompt)
        validation_result['completeness_score'] += prompt_score

        # Check context adequacy
        context_score = self._evaluate_context_adequacy(task)
        validation_result['completeness_score'] += context_score

        # Check file references
        files_score = self._evaluate_file_references(task.relevant_files)
        validation_result['completeness_score'] += files_score

        # Task-specific validation
        task_specific_score = self._validate_task_specific_requirements(task)
        validation_result['completeness_score'] += task_specific_score

        # Security validation
        security_issues = self._check_security_concerns(task)
        if security_issues:
            validation_result['errors'].extend(security_issues)
            validation_result['has_errors'] = True

        # Existing validation errors from parser
        if task.validation_errors:
            validation_result['errors'].extend(task.validation_errors)
            validation_result['has_errors'] = True

        # Generate improvement suggestions
        suggestions = self.suggest_improvements(task)
        validation_result['suggestions'] = suggestions

        # Final validation - respect testing mode for minimum score
        min_score = 25 if task.testing_mode else 50
        
        if validation_result['completeness_score'] < min_score:
            validation_result['is_valid'] = False
            validation_result['errors'].append(
                f"Task completeness score too low: {validation_result['completeness_score']}/100 (minimum: {min_score})"
            )
        
        # Add testing mode info to feedback if enabled
        if task.testing_mode:
            validation_result['warnings'] = validation_result.get('warnings', [])
            validation_result['warnings'].append("⚠️ Testing mode enabled - reduced validation requirements")

        # Generate feedback message
        validation_result['feedback'] = self._generate_feedback_message(validation_result, task)

        logger.info(
            "Task validation completed",
            is_valid=validation_result['is_valid'],
            score=validation_result['completeness_score'],
            errors_count=len(validation_result['errors'])
        )

        return validation_result

    def suggest_improvements(self, task: ParsedTask) -> List[str]:
        """Provide suggestions for improving task clarity"""
        suggestions = []

        # Prompt improvements
        if len(task.prompt) < 50:
            suggestions.append("Consider providing more detail in your prompt to help the agent understand your requirements better")

        if not any(word in task.prompt.lower() for word in ['what', 'how', 'why', 'analyze', 'implement', 'fix']):
            suggestions.append("Try to include specific action words like 'analyze', 'implement', 'fix', or questions starting with 'what', 'how', 'why'")

        # File reference improvements
        if not task.relevant_files and task.task_type in [TaskType.CODE_ANALYSIS, TaskType.REFACTORING, TaskType.BUG_INVESTIGATION]:
            suggestions.append("Consider specifying relevant files to help the agent focus on the right code")

        # Context improvements
        if not task.context and task.task_type in [TaskType.FEATURE_IMPLEMENTATION, TaskType.BUG_INVESTIGATION]:
            suggestions.append("Adding background context or constraints would help the agent provide better results")

        # Priority-specific suggestions
        if task.priority == TaskPriority.CRITICAL and task.estimated_complexity == "Complex":
            suggestions.append("For critical complex tasks, consider breaking them down into smaller, more manageable parts")

        # Task-specific suggestions
        if task.task_type == TaskType.FEATURE_IMPLEMENTATION and "test" not in task.prompt.lower():
            suggestions.append("Consider mentioning testing requirements for feature implementations")

        if task.task_type == TaskType.BUG_INVESTIGATION and "reproduce" not in task.prompt.lower():
            suggestions.append("For bug investigations, include steps to reproduce the issue if possible")

        return suggestions

    def check_file_accessibility(self, files: List[str], repo_info: Dict) -> Dict[str, bool]:
        """Verify that referenced files exist and are accessible"""
        accessibility_results = {}

        for file_path in files:
            if file_path.startswith('http'):
                # For URLs, we can't check accessibility without making requests
                accessibility_results[file_path] = True  # Assume accessible
                continue

            # Check if file path looks valid
            try:
                path = Path(file_path)
                # Basic validation - check if it's a reasonable file path
                is_valid = (
                    len(path.parts) > 0 and
                    not str(path).startswith('/') and  # No absolute paths
                    '..' not in str(path) and  # No directory traversal
                    any(pattern for pattern in self.common_file_patterns if re.match(pattern, str(path)))
                )
                accessibility_results[file_path] = is_valid
            except Exception:
                accessibility_results[file_path] = False

        return accessibility_results

    def _evaluate_prompt_quality(self, prompt: str) -> int:
        """Evaluate the quality of the prompt (0-40 points)"""
        score = 0

        # Length check
        if len(prompt) >= 100:
            score += 15
        elif len(prompt) >= 50:
            score += 10
        elif len(prompt) >= 20:
            score += 5

        # Clarity indicators
        clarity_words = ['analyze', 'implement', 'fix', 'create', 'update', 'review', 'explain']
        if any(word in prompt.lower() for word in clarity_words):
            score += 10

        # Question words (indicate clear intent)
        question_words = ['what', 'how', 'why', 'when', 'where', 'which']
        if any(word in prompt.lower() for word in question_words):
            score += 5

        # Specific requirements
        if any(word in prompt.lower() for word in ['should', 'need', 'must', 'require']):
            score += 5

        # Examples or specifics
        if any(char in prompt for char in ['example', 'specific', 'particular']):
            score += 5

        return min(score, 40)

    def _evaluate_context_adequacy(self, task: ParsedTask) -> int:
        """Evaluate if context is adequate for the task type (0-20 points)"""
        score = 0

        if task.context:
            score += 10  # Base score for having context

            # Length bonus
            if len(task.context) > 100:
                score += 5

            # Relevant keywords for context
            context_keywords = ['background', 'constraint', 'requirement', 'expectation', 'goal']
            if any(word in task.context.lower() for word in context_keywords):
                score += 5

        # Some task types need more context
        context_heavy_types = [TaskType.FEATURE_IMPLEMENTATION, TaskType.BUG_INVESTIGATION, TaskType.REFACTORING]
        if task.task_type in context_heavy_types and not task.context:
            score = max(0, score - 10)  # Penalty for missing context

        return min(score, 20)

    def _evaluate_file_references(self, files: List[str]) -> int:
        """Evaluate file references quality (0-20 points)"""
        score = 0

        if files:
            score += 10  # Base score for having file references

            # Quality of file references
            valid_files = 0
            for file_path in files:
                if any(re.match(pattern, file_path) for pattern in self.common_file_patterns):
                    valid_files += 1
                elif file_path.startswith('http') and 'github.com' in file_path:
                    valid_files += 1

            if valid_files == len(files):
                score += 10  # All files look valid

        return min(score, 20)

    def _validate_task_specific_requirements(self, task: ParsedTask) -> int:
        """Validate requirements specific to task type (0-20 points)"""
        score = 10  # Base score

        task_type = task.task_type
        prompt_lower = task.prompt.lower()

        if task_type == TaskType.CODE_ANALYSIS:
            if any(word in prompt_lower for word in ['performance', 'optimization', 'security', 'quality']):
                score += 5
            if task.relevant_files:
                score += 5

        elif task_type == TaskType.FEATURE_IMPLEMENTATION:
            if any(word in prompt_lower for word in ['specification', 'requirements', 'behavior']):
                score += 5
            if 'test' in prompt_lower:
                score += 5

        elif task_type == TaskType.BUG_INVESTIGATION:
            if any(word in prompt_lower for word in ['error', 'bug', 'issue', 'problem', 'fail']):
                score += 5
            if any(word in prompt_lower for word in ['reproduce', 'steps', 'expected', 'actual']):
                score += 5

        elif task_type == TaskType.REFACTORING:
            if any(word in prompt_lower for word in ['improve', 'clean', 'structure', 'maintainability']):
                score += 5
            if task.relevant_files:
                score += 5

        elif task_type == TaskType.DOCUMENTATION:
            if any(word in prompt_lower for word in ['document', 'explain', 'guide', 'readme']):
                score += 5

        return min(score, 20)

    def _check_security_concerns(self, task: ParsedTask) -> List[str]:
        """Check for potential security concerns in the task"""
        security_issues = []

        # Check prompt for sensitive information
        for pattern in self.security_patterns:
            if re.search(pattern, task.prompt, re.IGNORECASE):
                security_issues.append(f"Potential sensitive information detected in prompt: {pattern}")

        # Check context for sensitive information
        if task.context:
            for pattern in self.security_patterns:
                if re.search(pattern, task.context, re.IGNORECASE):
                    security_issues.append(f"Potential sensitive information detected in context: {pattern}")

        # Check for suspicious file patterns
        suspicious_files = ['.env', '.secret', 'id_rsa', 'private', 'credential']
        for file_path in task.relevant_files:
            if any(suspicious in file_path.lower() for suspicious in suspicious_files):
                security_issues.append(f"Potentially sensitive file referenced: {file_path}")

        return security_issues

    def _generate_feedback_message(self, validation_result: Dict[str, Any], task: ParsedTask) -> str:
        """Generate human-readable feedback message"""
        if validation_result['is_valid'] and not validation_result['has_errors']:
            return f"✅ Task validated successfully! Completeness score: {validation_result['completeness_score']}/100"

        feedback_parts = []

        if validation_result['has_errors']:
            feedback_parts.append("❌ **Issues Found:**")
            for error in validation_result['errors']:
                feedback_parts.append(f"- {error}")

        if validation_result['warnings']:
            feedback_parts.append("\n⚠️ **Warnings:**")
            for warning in validation_result['warnings']:
                feedback_parts.append(f"- {warning}")

        if validation_result['suggestions']:
            feedback_parts.append("\n💡 **Suggestions for Improvement:**")
            for suggestion in validation_result['suggestions']:
                feedback_parts.append(f"- {suggestion}")

        feedback_parts.append(f"\n📊 **Completeness Score:** {validation_result['completeness_score']}/100")

        return '\n'.join(feedback_parts)

    def is_ready_for_processing(self, task: ParsedTask) -> bool:
        """Check if task is ready for agent processing"""
        validation_result = self.validate_task_completeness(task)
        
        # In testing mode, allow processing even with security warnings (but not errors)
        if task.testing_mode:
            # Filter out security warnings in testing mode, but keep actual errors
            security_errors = [error for error in validation_result.get('errors', []) 
                             if 'sensitive' in error.lower() or 'security' in error.lower()]
            non_security_errors = [error for error in validation_result.get('errors', []) 
                                 if 'sensitive' not in error.lower() and 'security' not in error.lower()]
            
            # Allow processing if only security warnings exist and we're in testing mode
            return validation_result['is_valid'] and len(non_security_errors) == 0
        
        return validation_result['is_valid'] and not validation_result['has_errors']