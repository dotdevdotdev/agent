"""
Result parsing and GitHub integration system for Claude Code CLI outputs
"""

import re
import json
import structlog
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .claude_code_service import ClaudeExecutionResult, ClaudeProcessStatus
from .github_client import GitHubClient
from .git_service import GitService

logger = structlog.get_logger()


class ResultType(str, Enum):
    """Types of results that can be extracted"""
    CODE_CHANGES = "code_changes"
    ANALYSIS_REPORT = "analysis_report"
    DOCUMENTATION = "documentation"
    RECOMMENDATIONS = "recommendations"
    ERROR_FIXES = "error_fixes"
    TEST_CASES = "test_cases"
    IMPLEMENTATION_PLAN = "implementation_plan"


class OutputFormat(str, Enum):
    """Output format for GitHub presentation"""
    MARKDOWN_COMMENT = "markdown_comment"
    THREADED_COMMENTS = "threaded_comments"
    PULL_REQUEST = "pull_request"
    ISSUE_UPDATE = "issue_update"


@dataclass
class CodeChange:
    """Represents a code change suggestion or implementation"""
    file_path: str
    original_content: Optional[str] = None
    new_content: Optional[str] = None
    change_type: str = "modification"  # modification, creation, deletion
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    description: str = ""
    rationale: str = ""


@dataclass
class ParsedResult:
    """Parsed and structured result from Claude CLI output"""
    result_type: ResultType
    summary: str
    detailed_analysis: str = ""
    code_changes: List[CodeChange] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    file_references: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    confidence_score: float = 0.0
    warnings: List[str] = field(default_factory=list)


@dataclass
class GitHubOutput:
    """Formatted output ready for GitHub posting"""
    format_type: OutputFormat
    primary_comment: str
    additional_comments: List[Dict[str, str]] = field(default_factory=list)
    file_changes: Dict[str, str] = field(default_factory=dict)
    pr_title: Optional[str] = None
    pr_description: Optional[str] = None
    suggested_labels: List[str] = field(default_factory=list)


class ResultProcessorError(Exception):
    """Custom exception for result processor errors"""
    def __init__(self, message: str, execution_result: ClaudeExecutionResult = None):
        self.message = message
        self.execution_result = execution_result
        super().__init__(message)


class ResultProcessor:
    """Processes Claude Code CLI results and prepares GitHub integration"""

    def __init__(self, github_client: GitHubClient = None, git_service: GitService = None):
        self.github_client = github_client
        self.git_service = git_service
        
        # Patterns for parsing different types of content
        self.code_block_pattern = re.compile(r'```(\w+)?\n(.*?)\n```', re.DOTALL)
        self.file_reference_pattern = re.compile(r'`([^`]+\.(py|js|ts|md|yml|yaml|json|toml|txt))`')
        self.recommendation_pattern = re.compile(r'^(?:\d+\.|[-*•])\s+(.+)', re.MULTILINE)
        
        logger.info("Result processor initialized")

    async def process_result(self, 
                           execution_result: ClaudeExecutionResult,
                           job_id: str,
                           repository: str,
                           issue_number: int) -> ParsedResult:
        """Process Claude CLI execution result into structured format"""
        
        if execution_result.status != ClaudeProcessStatus.COMPLETED:
            raise ResultProcessorError(
                f"Cannot process failed execution: {execution_result.status}",
                execution_result
            )
        
        try:
            # Extract basic information
            output_text = execution_result.stdout
            
            # Determine result type
            result_type = self._determine_result_type(output_text, execution_result.command)
            
            # Parse content based on type
            parsed_result = self._parse_by_type(result_type, output_text, job_id)
            
            # Extract file references
            parsed_result.file_references = self._extract_file_references(output_text)
            
            # Calculate confidence score
            parsed_result.confidence_score = self._calculate_confidence_score(
                execution_result, parsed_result
            )
            
            # Add metadata
            parsed_result.metadata.update({
                "job_id": job_id,
                "repository": repository,
                "issue_number": issue_number,
                "execution_time": execution_result.execution_time,
                "claude_command": execution_result.command,
                "output_length": len(output_text)
            })
            
            logger.info(
                "Result processed successfully",
                job_id=job_id,
                result_type=result_type,
                code_changes=len(parsed_result.code_changes),
                confidence=parsed_result.confidence_score
            )
            
            return parsed_result
            
        except Exception as e:
            logger.error("Failed to process result", job_id=job_id, error=str(e))
            raise ResultProcessorError(f"Failed to process result: {str(e)}", execution_result)

    async def format_for_github(self,
                              parsed_result: ParsedResult,
                              output_format: OutputFormat = OutputFormat.MARKDOWN_COMMENT) -> GitHubOutput:
        """Format parsed result for GitHub posting"""
        
        try:
            if output_format == OutputFormat.MARKDOWN_COMMENT:
                return self._format_as_markdown_comment(parsed_result)
            elif output_format == OutputFormat.THREADED_COMMENTS:
                return self._format_as_threaded_comments(parsed_result)
            elif output_format == OutputFormat.PULL_REQUEST:
                return self._format_as_pull_request(parsed_result)
            elif output_format == OutputFormat.ISSUE_UPDATE:
                return self._format_as_issue_update(parsed_result)
            else:
                raise ResultProcessorError(f"Unsupported output format: {output_format}")
                
        except Exception as e:
            logger.error("Failed to format for GitHub", error=str(e))
            raise ResultProcessorError(f"Failed to format for GitHub: {str(e)}")

    async def post_to_github(self,
                           github_output: GitHubOutput,
                           repository: str,
                           issue_number: int) -> Dict[str, Any]:
        """Post formatted output to GitHub"""
        
        if not self.github_client:
            raise ResultProcessorError("GitHub client not configured")
        
        try:
            results = {"primary_comment": None, "additional_comments": [], "pr_created": None}
            
            # Post primary comment
            if github_output.primary_comment:
                comment_result = await self.github_client.create_comment(
                    repository, issue_number, github_output.primary_comment
                )
                results["primary_comment"] = comment_result
            
            # Post additional comments (for threaded format)
            for additional_comment in github_output.additional_comments:
                comment_result = await self.github_client.create_comment(
                    repository, issue_number, additional_comment["content"]
                )
                results["additional_comments"].append(comment_result)
            
            # Create PR if requested
            if github_output.format_type == OutputFormat.PULL_REQUEST and github_output.file_changes:
                # This would need integration with git service to create actual PR
                logger.info("PR creation requested but not yet implemented")
            
            # Add suggested labels
            if github_output.suggested_labels:
                try:
                    await self.github_client.add_labels(
                        repository, issue_number, github_output.suggested_labels
                    )
                except Exception as e:
                    logger.warning("Failed to add labels", error=str(e))
            
            logger.info(
                "Posted to GitHub successfully",
                repository=repository,
                issue_number=issue_number,
                format_type=github_output.format_type
            )
            
            return results
            
        except Exception as e:
            logger.error("Failed to post to GitHub", error=str(e))
            raise ResultProcessorError(f"Failed to post to GitHub: {str(e)}")

    def _determine_result_type(self, output_text: str, command: List[str]) -> ResultType:
        """Determine the type of result based on content and command"""
        output_lower = output_text.lower()
        
        # Check for code changes
        if self.code_block_pattern.search(output_text):
            return ResultType.CODE_CHANGES
        
        # Check for analysis keywords
        analysis_keywords = ['analysis', 'review', 'quality', 'performance', 'security']
        if any(keyword in output_lower for keyword in analysis_keywords):
            return ResultType.ANALYSIS_REPORT
        
        # Check for documentation
        doc_keywords = ['documentation', 'readme', 'guide', 'manual']
        if any(keyword in output_lower for keyword in doc_keywords):
            return ResultType.DOCUMENTATION
        
        # Check for recommendations
        if re.search(r'recommend|suggest|should|could', output_lower):
            return ResultType.RECOMMENDATIONS
        
        # Check for error fixes
        error_keywords = ['error', 'bug', 'fix', 'issue', 'problem']
        if any(keyword in output_lower for keyword in error_keywords):
            return ResultType.ERROR_FIXES
        
        # Check for test cases
        test_keywords = ['test', 'testing', 'assert', 'expect']
        if any(keyword in output_lower for keyword in test_keywords):
            return ResultType.TEST_CASES
        
        # Default to analysis report
        return ResultType.ANALYSIS_REPORT

    def _parse_by_type(self, result_type: ResultType, output_text: str, job_id: str) -> ParsedResult:
        """Parse content based on result type"""
        
        # Extract summary (first paragraph or first 200 characters)
        lines = output_text.strip().split('\n')
        summary = lines[0] if lines else output_text[:200]
        
        # Remove markdown headers from summary
        summary = re.sub(r'^#+\s*', '', summary.strip())
        
        parsed_result = ParsedResult(
            result_type=result_type,
            summary=summary,
            detailed_analysis=output_text
        )
        
        if result_type == ResultType.CODE_CHANGES:
            parsed_result.code_changes = self._extract_code_changes(output_text)
            # Also extract recommendations from code change results
            parsed_result.recommendations = self._extract_recommendations(output_text)
        
        if result_type in [ResultType.RECOMMENDATIONS, ResultType.ANALYSIS_REPORT]:
            parsed_result.recommendations = self._extract_recommendations(output_text)
        
        return parsed_result

    def _extract_code_changes(self, output_text: str) -> List[CodeChange]:
        """Extract code changes from output"""
        changes = []
        
        # Find all code blocks
        code_blocks = self.code_block_pattern.findall(output_text)
        
        for i, (language, code_content) in enumerate(code_blocks):
            # Try to extract file path from surrounding context
            file_path = self._guess_file_path(output_text, code_content, language)
            
            # Determine change type
            change_type = "modification"
            if "new file" in output_text.lower() or "create" in output_text.lower():
                change_type = "creation"
            elif "delete" in output_text.lower() or "remove" in output_text.lower():
                change_type = "deletion"
            
            # Extract description from surrounding text
            description = self._extract_change_description(output_text, code_content)
            
            changes.append(CodeChange(
                file_path=file_path or f"suggested_change_{i + 1}.{language or 'txt'}",
                new_content=code_content,
                change_type=change_type,
                description=description
            ))
        
        return changes

    def _extract_recommendations(self, output_text: str) -> List[str]:
        """Extract recommendations from output"""
        recommendations = []
        
        # Find numbered or bulleted lists
        matches = self.recommendation_pattern.findall(output_text)
        recommendations.extend(matches)
        
        # If no structured lists found, look for sentences with recommendation keywords
        if not recommendations:
            sentences = re.split(r'[.!?]+', output_text)
            for sentence in sentences:
                if re.search(r'\b(recommend|suggest|should|consider|improve)\b', sentence.lower()):
                    clean_sentence = sentence.strip()
                    if len(clean_sentence) > 10:  # Filter out very short matches
                        recommendations.append(clean_sentence)
        
        return recommendations[:10]  # Limit to top 10 recommendations

    def _extract_file_references(self, output_text: str) -> List[str]:
        """Extract file references from output"""
        matches = self.file_reference_pattern.findall(output_text)
        return list(set(match[0] for match in matches))  # Remove duplicates

    def _guess_file_path(self, full_text: str, code_content: str, language: str) -> str:
        """Guess file path from context"""
        # Look for file path mentions near the code block
        lines_before = full_text[:full_text.find(code_content)].split('\n')[-5:]
        lines_after = full_text[full_text.find(code_content) + len(code_content):].split('\n')[:5]
        
        context_lines = lines_before + lines_after
        
        for line in context_lines:
            # Look for file path patterns
            file_matches = re.findall(r'([^\s]+\.\w+)', line)
            for match in file_matches:
                if any(ext in match for ext in ['.py', '.js', '.ts', '.md', '.yml', '.yaml']):
                    return match
        
        # Fallback based on language
        extension_map = {
            'python': 'py',
            'javascript': 'js',
            'typescript': 'ts',
            'markdown': 'md',
            'yaml': 'yml',
            'json': 'json'
        }
        
        ext = extension_map.get(language, 'txt')
        return f"suggested_file.{ext}"

    def _extract_change_description(self, full_text: str, code_content: str) -> str:
        """Extract description for a code change"""
        # Find the code block in the full text
        code_block_match = re.search(re.escape(code_content), full_text)
        if not code_block_match:
            return "Code modification suggested"
        
        code_start = code_block_match.start()
        
        # Find text immediately before the code block
        before_text = full_text[:code_start]
        lines_before = before_text.split('\n')
        
        # Look for meaningful description in the last few lines
        description_lines = []
        for line in reversed(lines_before[-5:]):  # Check last 5 lines
            clean_line = re.sub(r'[#*`]', '', line).strip()
            if clean_line and not clean_line.startswith('```') and len(clean_line) > 5:
                description_lines.insert(0, clean_line)
                if len(' '.join(description_lines)) > 50:  # Stop when we have enough
                    break
        
        if description_lines:
            description = ' '.join(description_lines)
            return description[:200]  # Limit length
        
        return "Code modification suggested"

    def _calculate_confidence_score(self, 
                                   execution_result: ClaudeExecutionResult,
                                   parsed_result: ParsedResult) -> float:
        """Calculate confidence score for the result"""
        score = 0.5  # Base score
        
        # Execution success adds confidence
        if execution_result.status == ClaudeProcessStatus.COMPLETED:
            score += 0.2
        
        # Longer, more detailed output adds confidence
        output_length = len(execution_result.stdout)
        if output_length > 1000:
            score += 0.1
        if output_length > 5000:
            score += 0.1
        
        # Structured content adds confidence
        if parsed_result.code_changes:
            score += 0.1
        if parsed_result.recommendations:
            score += 0.1
        if parsed_result.file_references:
            score += 0.05
        
        # Fast execution (indicating Claude was confident) adds score
        if execution_result.execution_time < 30:
            score += 0.05
        
        return min(score, 1.0)

    def _format_as_markdown_comment(self, parsed_result: ParsedResult) -> GitHubOutput:
        """Format as single markdown comment"""
        
        # Build the comment
        comment_parts = []
        
        # Header with result type
        emoji_map = {
            ResultType.CODE_CHANGES: "💻",
            ResultType.ANALYSIS_REPORT: "📊",
            ResultType.DOCUMENTATION: "📚",
            ResultType.RECOMMENDATIONS: "💡",
            ResultType.ERROR_FIXES: "🔧",
            ResultType.TEST_CASES: "🧪",
            ResultType.IMPLEMENTATION_PLAN: "📋"
        }
        
        emoji = emoji_map.get(parsed_result.result_type, "🤖")
        comment_parts.append(f"## {emoji} {parsed_result.result_type.value.replace('_', ' ').title()}")
        comment_parts.append("")
        
        # Summary
        comment_parts.append(f"**Summary:** {parsed_result.summary}")
        comment_parts.append("")
        
        # Confidence indicator
        confidence_emoji = "🟢" if parsed_result.confidence_score > 0.8 else "🟡" if parsed_result.confidence_score > 0.6 else "🔴"
        comment_parts.append(f"**Confidence:** {confidence_emoji} {parsed_result.confidence_score:.0%}")
        comment_parts.append("")
        
        # Code changes
        if parsed_result.code_changes:
            comment_parts.append("### 💻 Proposed Changes")
            comment_parts.append("")
            
            for i, change in enumerate(parsed_result.code_changes, 1):
                comment_parts.append(f"#### {i}. {change.file_path}")
                if change.description:
                    comment_parts.append(f"*{change.description}*")
                comment_parts.append("")
                comment_parts.append(f"```{self._get_language_from_extension(change.file_path)}")
                comment_parts.append(change.new_content or "")
                comment_parts.append("```")
                comment_parts.append("")
        
        # Recommendations
        if parsed_result.recommendations:
            comment_parts.append("### 💡 Recommendations")
            comment_parts.append("")
            for i, rec in enumerate(parsed_result.recommendations, 1):
                comment_parts.append(f"{i}. {rec}")
            comment_parts.append("")
        
        # File references
        if parsed_result.file_references:
            comment_parts.append("### 📁 Referenced Files")
            comment_parts.append("")
            for file_ref in parsed_result.file_references:
                comment_parts.append(f"- `{file_ref}`")
            comment_parts.append("")
        
        # Warnings
        if parsed_result.warnings:
            comment_parts.append("### ⚠️ Warnings")
            comment_parts.append("")
            for warning in parsed_result.warnings:
                comment_parts.append(f"- {warning}")
            comment_parts.append("")
        
        # Footer
        comment_parts.append("---")
        comment_parts.append("*Generated by Claude Code Agent*")
        
        # Determine suggested labels
        labels = self._suggest_labels(parsed_result)
        
        return GitHubOutput(
            format_type=OutputFormat.MARKDOWN_COMMENT,
            primary_comment="\n".join(comment_parts),
            suggested_labels=labels
        )

    def _format_as_threaded_comments(self, parsed_result: ParsedResult) -> GitHubOutput:
        """Format as multiple threaded comments"""
        
        # Main comment with summary
        main_comment = self._format_as_markdown_comment(parsed_result).primary_comment
        
        additional_comments = []
        
        # Separate comments for each code change
        for i, change in enumerate(parsed_result.code_changes):
            comment_content = f"### Code Change {i + 1}: {change.file_path}\n\n"
            if change.description:
                comment_content += f"{change.description}\n\n"
            comment_content += f"```{self._get_language_from_extension(change.file_path)}\n"
            comment_content += f"{change.new_content}\n```"
            
            additional_comments.append({"content": comment_content})
        
        return GitHubOutput(
            format_type=OutputFormat.THREADED_COMMENTS,
            primary_comment=main_comment,
            additional_comments=additional_comments,
            suggested_labels=self._suggest_labels(parsed_result)
        )

    def _format_as_pull_request(self, parsed_result: ParsedResult) -> GitHubOutput:
        """Format as pull request content"""
        
        if not parsed_result.code_changes:
            raise ResultProcessorError("Cannot create PR without code changes")
        
        # PR title
        pr_title = f"[Agent] {parsed_result.summary[:60]}..."
        
        # PR description
        description_parts = []
        description_parts.append(f"## {parsed_result.result_type.value.replace('_', ' ').title()}")
        description_parts.append("")
        description_parts.append(parsed_result.summary)
        description_parts.append("")
        
        if parsed_result.recommendations:
            description_parts.append("## Recommendations")
            for rec in parsed_result.recommendations:
                description_parts.append(f"- {rec}")
            description_parts.append("")
        
        description_parts.append("---")
        description_parts.append("*This PR was generated by Claude Code Agent*")
        
        # File changes for PR
        file_changes = {}
        for change in parsed_result.code_changes:
            file_changes[change.file_path] = change.new_content or ""
        
        return GitHubOutput(
            format_type=OutputFormat.PULL_REQUEST,
            primary_comment="\n".join(description_parts),
            file_changes=file_changes,
            pr_title=pr_title,
            pr_description="\n".join(description_parts),
            suggested_labels=self._suggest_labels(parsed_result)
        )

    def _format_as_issue_update(self, parsed_result: ParsedResult) -> GitHubOutput:
        """Format as issue update"""
        
        # Simple status update comment
        comment = f"## Status Update\n\n"
        comment += f"Task completed: {parsed_result.summary}\n\n"
        
        if parsed_result.code_changes:
            comment += f"**Code changes proposed:** {len(parsed_result.code_changes)}\n"
        if parsed_result.recommendations:
            comment += f"**Recommendations provided:** {len(parsed_result.recommendations)}\n"
        
        comment += f"\n**Confidence:** {parsed_result.confidence_score:.0%}\n"
        
        return GitHubOutput(
            format_type=OutputFormat.ISSUE_UPDATE,
            primary_comment=comment,
            suggested_labels=self._suggest_labels(parsed_result) + ["agent:completed"]
        )

    def _suggest_labels(self, parsed_result: ParsedResult) -> List[str]:
        """Suggest appropriate GitHub labels"""
        labels = []
        
        # Result type based labels
        type_labels = {
            ResultType.CODE_CHANGES: ["enhancement", "code-change"],
            ResultType.ANALYSIS_REPORT: ["analysis"],
            ResultType.DOCUMENTATION: ["documentation"],
            ResultType.RECOMMENDATIONS: ["improvement"],
            ResultType.ERROR_FIXES: ["bug", "fix"],
            ResultType.TEST_CASES: ["testing"],
            ResultType.IMPLEMENTATION_PLAN: ["planning"]
        }
        
        labels.extend(type_labels.get(parsed_result.result_type, []))
        
        # Confidence based labels
        if parsed_result.confidence_score > 0.8:
            labels.append("high-confidence")
        elif parsed_result.confidence_score < 0.5:
            labels.append("needs-review")
        
        return labels

    def _get_language_from_extension(self, file_path: str) -> str:
        """Get syntax highlighting language from file extension"""
        extension_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.md': 'markdown',
            '.yml': 'yaml',
            '.yaml': 'yaml',
            '.json': 'json',
            '.html': 'html',
            '.css': 'css',
            '.sh': 'bash'
        }
        
        ext = Path(file_path).suffix.lower()
        return extension_map.get(ext, 'text')

    def format_simple_response(self, parsed_result: 'ParsedResult', parsed_task) -> 'GitHubOutput':
        """Format a simple text response for general questions"""
        
        # Extract the response from stdout (stored in metadata)
        response_text = parsed_result.metadata.get("raw_output", "").strip()
        
        if not response_text:
            response_text = "I apologize, but I wasn't able to generate a response. Please try rephrasing your question."
        
        # Format as a clean GitHub comment
        formatted_response = f"""## 🤖 Response

{response_text}

---
*This response was generated using Claude AI in general question mode.*
*Processing time: {parsed_result.metadata.get('execution_time', 0):.2f} seconds*
"""
        
        # Create simple GitHub output
        return GitHubOutput(
            format_type=OutputFormat.MARKDOWN_COMMENT,
            primary_comment=formatted_response,
            suggested_labels=["agent:completed"]
        )