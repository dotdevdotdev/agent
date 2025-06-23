"""
Intelligent error classification and recovery recommendation
"""

import re
import structlog
from enum import Enum
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = structlog.get_logger()


class ErrorSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErrorCategory(str, Enum):
    PARSING_ERROR = "parsing_error"
    VALIDATION_ERROR = "validation_error"
    API_ERROR = "api_error"
    RATE_LIMIT = "rate_limit"
    PERMISSION_ERROR = "permission_error"
    TIMEOUT_ERROR = "timeout_error"
    PROCESSING_ERROR = "processing_error"
    NETWORK_ERROR = "network_error"
    CONFIGURATION_ERROR = "configuration_error"
    RESOURCE_ERROR = "resource_error"
    USER_ERROR = "user_error"
    UNKNOWN_ERROR = "unknown_error"


class RetryStrategy(str, Enum):
    IMMEDIATE = "immediate"
    EXPONENTIAL_BACKOFF = "exponential_backoff"
    LINEAR_BACKOFF = "linear_backoff"
    FIXED_DELAY = "fixed_delay"
    NO_RETRY = "no_retry"
    USER_INTERVENTION = "user_intervention"


@dataclass
class ErrorAnalysis:
    category: ErrorCategory
    severity: ErrorSeverity
    is_retryable: bool
    retry_strategy: RetryStrategy
    max_retries: int
    escalation_required: bool
    user_message: str
    technical_details: str
    recovery_actions: List[str]
    error_patterns: List[str]
    context_hints: Dict[str, Any]
    similar_errors_count: int = 0


class ErrorClassifier:
    """Classifies errors and recommends recovery strategies"""

    def __init__(self):
        self.error_patterns = self._initialize_error_patterns()
        self.severity_rules = self._initialize_severity_rules()
        self.retry_rules = self._initialize_retry_rules()
        self.error_history: Dict[str, List[Dict[str, Any]]] = {}

    def classify_error(self, error: Exception, context: Dict[str, Any] = None) -> ErrorAnalysis:
        """Classify error and determine recovery strategy"""
        logger.info("Classifying error", error_type=type(error).__name__)

        error_str = str(error)
        context = context or {}

        # Determine error category
        category = self._categorize_error(error, error_str, context)
        
        # Determine severity
        severity = self._determine_severity(error, category, context)
        
        # Determine retry strategy
        retry_info = self._determine_retry_strategy(category, severity, context)
        
        # Generate user-friendly message
        user_message = self._generate_user_message(error, category, severity)
        
        # Generate technical details
        technical_details = self._generate_technical_details(error, context)
        
        # Determine recovery actions
        recovery_actions = self._determine_recovery_actions(category, severity, context)
        
        # Check for similar errors
        similar_count = self._count_similar_errors(error_str, context)
        
        # Determine if escalation is needed
        escalation_required = self._should_escalate(category, severity, similar_count, context)

        analysis = ErrorAnalysis(
            category=category,
            severity=severity,
            is_retryable=retry_info['is_retryable'],
            retry_strategy=retry_info['strategy'],
            max_retries=retry_info['max_retries'],
            escalation_required=escalation_required,
            user_message=user_message,
            technical_details=technical_details,
            recovery_actions=recovery_actions,
            error_patterns=self._extract_error_patterns(error_str),
            context_hints=self._extract_context_hints(context),
            similar_errors_count=similar_count
        )

        # Record error for pattern analysis
        self._record_error(error, analysis, context)

        logger.info(
            "Error classification completed",
            category=analysis.category,
            severity=analysis.severity,
            retryable=analysis.is_retryable,
            escalation_required=analysis.escalation_required
        )

        return analysis

    def should_retry(self, error: Exception, attempt_count: int, 
                    previous_analysis: ErrorAnalysis = None) -> bool:
        """Determine if error should trigger a retry"""
        
        if previous_analysis:
            analysis = previous_analysis
        else:
            analysis = self.classify_error(error)

        if not analysis.is_retryable:
            return False

        if attempt_count >= analysis.max_retries:
            return False

        # Check for escalation conditions
        if analysis.escalation_required and attempt_count >= 1:
            return False

        # Special handling for certain error types
        if analysis.category == ErrorCategory.RATE_LIMIT:
            # Always retry rate limits with backoff
            return attempt_count < 5
        
        if analysis.category == ErrorCategory.NETWORK_ERROR:
            # Retry network errors with exponential backoff
            return attempt_count < 3

        return True

    def get_retry_delay(self, error: Exception, attempt_count: int,
                       previous_analysis: ErrorAnalysis = None) -> int:
        """Calculate delay before retry (in seconds)"""
        
        if previous_analysis:
            analysis = previous_analysis
        else:
            analysis = self.classify_error(error)

        strategy = analysis.retry_strategy
        
        if strategy == RetryStrategy.IMMEDIATE:
            return 0
        elif strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
            return min(300, 2 ** attempt_count)  # Cap at 5 minutes
        elif strategy == RetryStrategy.LINEAR_BACKOFF:
            return min(120, attempt_count * 30)  # Cap at 2 minutes
        elif strategy == RetryStrategy.FIXED_DELAY:
            return 60  # 1 minute
        else:
            return 0

    def get_error_statistics(self, time_window_hours: int = 24) -> Dict[str, Any]:
        """Get error statistics for monitoring"""
        cutoff_time = datetime.now() - timedelta(hours=time_window_hours)
        
        recent_errors = []
        for job_id, errors in self.error_history.items():
            for error_record in errors:
                if error_record['timestamp'] > cutoff_time:
                    recent_errors.append(error_record)

        # Calculate statistics
        total_errors = len(recent_errors)
        categories = {}
        severities = {}
        retryable_count = 0
        escalated_count = 0

        for error_record in recent_errors:
            analysis = error_record['analysis']
            
            # Count by category
            category = analysis.category
            categories[category] = categories.get(category, 0) + 1
            
            # Count by severity
            severity = analysis.severity
            severities[severity] = severities.get(severity, 0) + 1
            
            # Count retryable and escalated
            if analysis.is_retryable:
                retryable_count += 1
            if analysis.escalation_required:
                escalated_count += 1

        return {
            'total_errors': total_errors,
            'categories': categories,
            'severities': severities,
            'retryable_count': retryable_count,
            'escalated_count': escalated_count,
            'error_rate': total_errors / max(1, time_window_hours),
            'most_common_category': max(categories.items(), key=lambda x: x[1])[0] if categories else None
        }

    def _categorize_error(self, error: Exception, error_str: str, 
                         context: Dict[str, Any]) -> ErrorCategory:
        """Categorize the error based on patterns and context"""
        
        error_str_lower = error_str.lower()
        error_type = type(error).__name__.lower()

        # Check specific error patterns
        for category, patterns in self.error_patterns.items():
            for pattern in patterns:
                if re.search(pattern, error_str_lower, re.IGNORECASE):
                    return category

        # Check error type
        type_mappings = {
            'validationerror': ErrorCategory.VALIDATION_ERROR,
            'permissionerror': ErrorCategory.PERMISSION_ERROR,
            'timeouterror': ErrorCategory.TIMEOUT_ERROR,
            'connectionerror': ErrorCategory.NETWORK_ERROR,
            'httperror': ErrorCategory.API_ERROR,
            'parseerror': ErrorCategory.PARSING_ERROR,
            'configurationerror': ErrorCategory.CONFIGURATION_ERROR,
            'memoryerror': ErrorCategory.RESOURCE_ERROR,
            'filenotfounderror': ErrorCategory.USER_ERROR
        }

        for error_name, category in type_mappings.items():
            if error_name in error_type:
                return category

        # Check context for additional hints
        if context.get('operation') == 'github_api':
            return ErrorCategory.API_ERROR
        elif context.get('operation') == 'validation':
            return ErrorCategory.VALIDATION_ERROR
        elif context.get('operation') == 'parsing':
            return ErrorCategory.PARSING_ERROR

        return ErrorCategory.UNKNOWN_ERROR

    def _determine_severity(self, error: Exception, category: ErrorCategory,
                          context: Dict[str, Any]) -> ErrorSeverity:
        """Determine error severity"""
        
        # Check severity rules
        severity_rules = self.severity_rules.get(category, {})
        
        # Critical errors
        if category in [ErrorCategory.PERMISSION_ERROR, ErrorCategory.CONFIGURATION_ERROR]:
            return ErrorSeverity.CRITICAL
        
        # High severity errors
        if category in [ErrorCategory.API_ERROR, ErrorCategory.RESOURCE_ERROR]:
            return ErrorSeverity.HIGH
        
        # Medium severity errors
        if category in [ErrorCategory.PROCESSING_ERROR, ErrorCategory.TIMEOUT_ERROR]:
            return ErrorSeverity.MEDIUM
        
        # Check for specific patterns in error message
        error_str = str(error).lower()
        if any(word in error_str for word in ['critical', 'fatal', 'corrupt']):
            return ErrorSeverity.CRITICAL
        elif any(word in error_str for word in ['failed', 'error', 'exception']):
            return ErrorSeverity.HIGH
        elif any(word in error_str for word in ['warning', 'timeout', 'retry']):
            return ErrorSeverity.MEDIUM
        
        # Check context for severity hints
        if context.get('retry_count', 0) > 2:
            return ErrorSeverity.HIGH
        
        return ErrorSeverity.LOW

    def _determine_retry_strategy(self, category: ErrorCategory, severity: ErrorSeverity,
                                context: Dict[str, Any]) -> Dict[str, Any]:
        """Determine retry strategy and parameters"""
        
        retry_rules = self.retry_rules.get(category, {})
        
        # Default values
        is_retryable = True
        strategy = RetryStrategy.EXPONENTIAL_BACKOFF
        max_retries = 3

        # Category-specific rules
        if category == ErrorCategory.RATE_LIMIT:
            strategy = RetryStrategy.EXPONENTIAL_BACKOFF
            max_retries = 5
        elif category == ErrorCategory.NETWORK_ERROR:
            strategy = RetryStrategy.EXPONENTIAL_BACKOFF
            max_retries = 3
        elif category == ErrorCategory.TIMEOUT_ERROR:
            strategy = RetryStrategy.LINEAR_BACKOFF
            max_retries = 2
        elif category in [ErrorCategory.PERMISSION_ERROR, ErrorCategory.CONFIGURATION_ERROR]:
            is_retryable = False
            strategy = RetryStrategy.NO_RETRY
            max_retries = 0
        elif category == ErrorCategory.USER_ERROR:
            is_retryable = False
            strategy = RetryStrategy.USER_INTERVENTION
            max_retries = 0
        elif category == ErrorCategory.VALIDATION_ERROR:
            is_retryable = False
            strategy = RetryStrategy.USER_INTERVENTION
            max_retries = 0

        # Severity adjustments
        if severity == ErrorSeverity.CRITICAL:
            is_retryable = False
            strategy = RetryStrategy.NO_RETRY
        elif severity == ErrorSeverity.HIGH:
            max_retries = min(max_retries, 2)

        return {
            'is_retryable': is_retryable,
            'strategy': strategy,
            'max_retries': max_retries
        }

    def _generate_user_message(self, error: Exception, category: ErrorCategory,
                             severity: ErrorSeverity) -> str:
        """Generate user-friendly error message"""
        
        category_messages = {
            ErrorCategory.PARSING_ERROR: "There was an issue understanding your request format.",
            ErrorCategory.VALIDATION_ERROR: "Your task request needs some corrections before I can proceed.",
            ErrorCategory.API_ERROR: "I encountered an issue communicating with GitHub.",
            ErrorCategory.RATE_LIMIT: "I'm being rate-limited by GitHub. I'll retry shortly.",
            ErrorCategory.PERMISSION_ERROR: "I don't have the necessary permissions to complete this task.",
            ErrorCategory.TIMEOUT_ERROR: "The task took longer than expected and timed out.",
            ErrorCategory.PROCESSING_ERROR: "An error occurred while processing your task.",
            ErrorCategory.NETWORK_ERROR: "There was a network connectivity issue.",
            ErrorCategory.CONFIGURATION_ERROR: "There's a configuration issue that needs to be resolved.",
            ErrorCategory.RESOURCE_ERROR: "I don't have sufficient resources to complete this task.",
            ErrorCategory.USER_ERROR: "There's an issue with the information provided.",
            ErrorCategory.UNKNOWN_ERROR: "An unexpected error occurred."
        }

        base_message = category_messages.get(category, "An error occurred.")
        
        # Add severity context
        if severity == ErrorSeverity.CRITICAL:
            base_message = f"🚨 Critical Issue: {base_message}"
        elif severity == ErrorSeverity.HIGH:
            base_message = f"❗ {base_message}"
        elif severity == ErrorSeverity.MEDIUM:
            base_message = f"⚠️ {base_message}"

        return base_message

    def _generate_technical_details(self, error: Exception, context: Dict[str, Any]) -> str:
        """Generate technical details for debugging"""
        
        details = [
            f"Error Type: {type(error).__name__}",
            f"Error Message: {str(error)}",
            f"Timestamp: {datetime.now().isoformat()}"
        ]

        if context.get('operation'):
            details.append(f"Operation: {context['operation']}")
        
        if context.get('component'):
            details.append(f"Component: {context['component']}")
        
        if context.get('job_id'):
            details.append(f"Job ID: {context['job_id']}")

        if context.get('retry_count'):
            details.append(f"Retry Count: {context['retry_count']}")

        return '\n'.join(details)

    def _determine_recovery_actions(self, category: ErrorCategory, severity: ErrorSeverity,
                                  context: Dict[str, Any]) -> List[str]:
        """Determine recovery actions"""
        
        actions = []

        if category == ErrorCategory.VALIDATION_ERROR:
            actions.extend([
                "Review your task description for completeness",
                "Ensure all required fields are filled out",
                "Check that file references are correct",
                "Comment '/retry' after making corrections"
            ])
        elif category == ErrorCategory.PERMISSION_ERROR:
            actions.extend([
                "Check that the agent has necessary repository permissions",
                "Verify the GitHub token has appropriate scopes",
                "Contact a repository administrator if needed"
            ])
        elif category == ErrorCategory.RATE_LIMIT:
            actions.extend([
                "The agent will automatically retry with appropriate delays",
                "No action needed - just wait for the retry"
            ])
        elif category == ErrorCategory.TIMEOUT_ERROR:
            actions.extend([
                "The task may be too complex for automatic processing",
                "Consider breaking it into smaller parts",
                "Comment '/retry' to attempt again",
                "Comment '/escalate' for human review"
            ])
        elif category == ErrorCategory.NETWORK_ERROR:
            actions.extend([
                "Check your internet connection",
                "The agent will automatically retry",
                "Comment '/escalate' if the issue persists"
            ])
        else:
            actions.extend([
                "Comment '/retry' to attempt the task again",
                "Comment '/escalate' to escalate to human review",
                "Provide additional context if available"
            ])

        return actions

    def _count_similar_errors(self, error_str: str, context: Dict[str, Any]) -> int:
        """Count similar errors in recent history"""
        job_id = context.get('job_id', 'unknown')
        
        if job_id not in self.error_history:
            return 0

        similar_count = 0
        for error_record in self.error_history[job_id]:
            if self._are_errors_similar(error_str, error_record['error_str']):
                similar_count += 1

        return similar_count

    def _should_escalate(self, category: ErrorCategory, severity: ErrorSeverity,
                       similar_count: int, context: Dict[str, Any]) -> bool:
        """Determine if error should be escalated"""
        
        # Always escalate critical errors
        if severity == ErrorSeverity.CRITICAL:
            return True
        
        # Escalate permission and configuration errors
        if category in [ErrorCategory.PERMISSION_ERROR, ErrorCategory.CONFIGURATION_ERROR]:
            return True
        
        # Escalate if too many similar errors
        if similar_count >= 3:
            return True
        
        # Escalate if too many retries
        if context.get('retry_count', 0) >= 3:
            return True

        return False

    def _record_error(self, error: Exception, analysis: ErrorAnalysis, 
                     context: Dict[str, Any]) -> None:
        """Record error for pattern analysis"""
        job_id = context.get('job_id', 'unknown')
        
        if job_id not in self.error_history:
            self.error_history[job_id] = []

        error_record = {
            'timestamp': datetime.now(),
            'error_str': str(error),
            'error_type': type(error).__name__,
            'analysis': analysis,
            'context': context
        }

        self.error_history[job_id].append(error_record)
        
        # Keep only recent errors (last 100 per job)
        if len(self.error_history[job_id]) > 100:
            self.error_history[job_id] = self.error_history[job_id][-100:]

    def _extract_error_patterns(self, error_str: str) -> List[str]:
        """Extract patterns from error string"""
        patterns = []
        
        # Extract quoted strings
        quoted_pattern = r'"([^"]+)"'
        quoted_matches = re.findall(quoted_pattern, error_str)
        patterns.extend(quoted_matches)
        
        # Extract file paths
        path_pattern = r'([a-zA-Z0-9_/\-\.]+\.[a-zA-Z]+)'
        path_matches = re.findall(path_pattern, error_str)
        patterns.extend(path_matches)
        
        # Extract URLs
        url_pattern = r'https?://[^\s]+'
        url_matches = re.findall(url_pattern, error_str)
        patterns.extend(url_matches)

        return patterns[:5]  # Limit to 5 patterns

    def _extract_context_hints(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Extract useful context hints"""
        hints = {}
        
        if context.get('user_preferences'):
            hints['user_prefers_detailed_errors'] = context['user_preferences'].get('wants_explanations', False)
        
        if context.get('task_complexity'):
            hints['task_complexity'] = context['task_complexity']
        
        if context.get('time_of_day'):
            hints['time_of_day'] = context['time_of_day']

        return hints

    def _are_errors_similar(self, error1: str, error2: str) -> bool:
        """Check if two errors are similar"""
        # Simple similarity check based on common words
        words1 = set(error1.lower().split())
        words2 = set(error2.lower().split())
        
        common_words = words1.intersection(words2)
        total_words = words1.union(words2)
        
        if len(total_words) == 0:
            return False
        
        similarity = len(common_words) / len(total_words)
        return similarity > 0.6  # 60% similarity threshold

    def _initialize_error_patterns(self) -> Dict[ErrorCategory, List[str]]:
        """Initialize error patterns for categorization"""
        return {
            ErrorCategory.PARSING_ERROR: [
                r'parse.*error',
                r'invalid.*syntax',
                r'malformed.*',
                r'unexpected.*token',
                r'json.*decode'
            ],
            ErrorCategory.VALIDATION_ERROR: [
                r'validation.*failed',
                r'invalid.*input',
                r'required.*field',
                r'missing.*parameter',
                r'constraint.*violation'
            ],
            ErrorCategory.API_ERROR: [
                r'api.*error',
                r'http.*error',
                r'github.*api',
                r'status.*code.*[45]\d\d',
                r'response.*error'
            ],
            ErrorCategory.RATE_LIMIT: [
                r'rate.*limit',
                r'too.*many.*requests',
                r'quota.*exceeded',
                r'limit.*reached',
                r'403.*forbidden.*rate'
            ],
            ErrorCategory.PERMISSION_ERROR: [
                r'permission.*denied',
                r'access.*denied',
                r'unauthorized',
                r'forbidden',
                r'insufficient.*permissions'
            ],
            ErrorCategory.TIMEOUT_ERROR: [
                r'timeout',
                r'timed.*out',
                r'connection.*timeout',
                r'read.*timeout',
                r'operation.*timeout'
            ],
            ErrorCategory.NETWORK_ERROR: [
                r'network.*error',
                r'connection.*error',
                r'dns.*error',
                r'host.*unreachable',
                r'connection.*refused'
            ],
            ErrorCategory.CONFIGURATION_ERROR: [
                r'configuration.*error',
                r'config.*missing',
                r'environment.*variable',
                r'setting.*invalid',
                r'missing.*token'
            ],
            ErrorCategory.RESOURCE_ERROR: [
                r'memory.*error',
                r'disk.*space',
                r'resource.*unavailable',
                r'out.*of.*memory',
                r'storage.*full'
            ],
            ErrorCategory.USER_ERROR: [
                r'file.*not.*found',
                r'invalid.*path',
                r'user.*error',
                r'bad.*request',
                r'invalid.*format'
            ]
        }

    def _initialize_severity_rules(self) -> Dict[ErrorCategory, Dict[str, Any]]:
        """Initialize severity determination rules"""
        return {
            ErrorCategory.PERMISSION_ERROR: {'default': ErrorSeverity.CRITICAL},
            ErrorCategory.CONFIGURATION_ERROR: {'default': ErrorSeverity.CRITICAL},
            ErrorCategory.API_ERROR: {'default': ErrorSeverity.HIGH},
            ErrorCategory.PROCESSING_ERROR: {'default': ErrorSeverity.MEDIUM},
            ErrorCategory.VALIDATION_ERROR: {'default': ErrorSeverity.MEDIUM},
            ErrorCategory.TIMEOUT_ERROR: {'default': ErrorSeverity.MEDIUM},
            ErrorCategory.RATE_LIMIT: {'default': ErrorSeverity.LOW},
            ErrorCategory.USER_ERROR: {'default': ErrorSeverity.LOW}
        }

    def _initialize_retry_rules(self) -> Dict[ErrorCategory, Dict[str, Any]]:
        """Initialize retry strategy rules"""
        return {
            ErrorCategory.RATE_LIMIT: {
                'retryable': True,
                'strategy': RetryStrategy.EXPONENTIAL_BACKOFF,
                'max_retries': 5
            },
            ErrorCategory.NETWORK_ERROR: {
                'retryable': True,
                'strategy': RetryStrategy.EXPONENTIAL_BACKOFF,
                'max_retries': 3
            },
            ErrorCategory.TIMEOUT_ERROR: {
                'retryable': True,
                'strategy': RetryStrategy.LINEAR_BACKOFF,
                'max_retries': 2
            },
            ErrorCategory.API_ERROR: {
                'retryable': True,
                'strategy': RetryStrategy.EXPONENTIAL_BACKOFF,
                'max_retries': 2
            },
            ErrorCategory.PERMISSION_ERROR: {
                'retryable': False,
                'strategy': RetryStrategy.NO_RETRY,
                'max_retries': 0
            },
            ErrorCategory.CONFIGURATION_ERROR: {
                'retryable': False,
                'strategy': RetryStrategy.NO_RETRY,
                'max_retries': 0
            },
            ErrorCategory.VALIDATION_ERROR: {
                'retryable': False,
                'strategy': RetryStrategy.USER_INTERVENTION,
                'max_retries': 0
            },
            ErrorCategory.USER_ERROR: {
                'retryable': False,
                'strategy': RetryStrategy.USER_INTERVENTION,
                'max_retries': 0
            }
        }