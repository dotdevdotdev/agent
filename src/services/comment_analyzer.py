"""
Analyzes user comments for intent and extracts actionable information
"""

import re
import structlog
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from .issue_parser import ParsedTask

logger = structlog.get_logger()


class CommentIntent(str, Enum):
    CANCEL = "cancel"
    RETRY = "retry"
    ESCALATE = "escalate"
    FEEDBACK_RESPONSE = "feedback_response"
    CLARIFICATION = "clarification"
    APPROVAL = "approval"
    MODIFICATION_REQUEST = "modification_request"
    QUESTION = "question"
    GENERAL_COMMENT = "general_comment"


class SentimentType(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    FRUSTRATED = "frustrated"
    SATISFIED = "satisfied"


@dataclass
class CommentAnalysis:
    intent: CommentIntent
    confidence: float  # 0.0 to 1.0
    sentiment: SentimentType
    extracted_commands: List[str]
    feedback_responses: Dict[str, str]
    clarifications: Dict[str, Any]
    urgency_level: str  # low, medium, high
    key_phrases: List[str]
    mentioned_files: List[str]
    mentioned_users: List[str]
    questions: List[str]
    action_items: List[str]


class CommentAnalyzer:
    """Analyzes GitHub comments for user intent and commands"""

    def __init__(self):
        self.command_patterns = self._initialize_command_patterns()
        self.intent_patterns = self._initialize_intent_patterns()
        self.sentiment_indicators = self._initialize_sentiment_indicators()
        self.urgency_keywords = self._initialize_urgency_keywords()

    def analyze_user_intent(self, comment_body: str) -> CommentAnalysis:
        """Analyze comment to determine user intent"""
        logger.info("Analyzing comment intent", comment_length=len(comment_body))

        comment_lower = comment_body.lower().strip()
        
        # Extract commands first
        commands = self.detect_commands(comment_body)
        
        # Determine primary intent
        intent, confidence = self._determine_primary_intent(comment_body, commands)
        
        # Analyze sentiment
        sentiment = self._analyze_sentiment(comment_body)
        
        # Extract various elements
        feedback_responses = self._extract_feedback_responses(comment_body)
        clarifications = self._extract_clarifications(comment_body)
        urgency = self._assess_urgency(comment_body)
        key_phrases = self._extract_key_phrases(comment_body)
        mentioned_files = self._extract_file_mentions(comment_body)
        mentioned_users = self._extract_user_mentions(comment_body)
        questions = self._extract_questions(comment_body)
        action_items = self._extract_action_items(comment_body)

        analysis = CommentAnalysis(
            intent=intent,
            confidence=confidence,
            sentiment=sentiment,
            extracted_commands=[cmd['command'] for cmd in commands],
            feedback_responses=feedback_responses,
            clarifications=clarifications,
            urgency_level=urgency,
            key_phrases=key_phrases,
            mentioned_files=mentioned_files,
            mentioned_users=mentioned_users,
            questions=questions,
            action_items=action_items
        )

        logger.info(
            "Comment analysis completed",
            intent=analysis.intent,
            confidence=analysis.confidence,
            sentiment=analysis.sentiment,
            commands_count=len(analysis.extracted_commands)
        )

        return analysis

    def extract_feedback_responses(self, comment_body: str, 
                                 pending_questions: List[str]) -> Dict[str, str]:
        """Extract responses to pending feedback requests"""
        responses = {}
        
        # Look for numbered responses (1. answer, 2. answer, etc.)
        numbered_pattern = r'^(\d+)\.?\s*(.+)$'
        for line in comment_body.split('\n'):
            match = re.match(numbered_pattern, line.strip(), re.MULTILINE)
            if match:
                option_num = int(match.group(1))
                response = match.group(2).strip()
                responses[f"option_{option_num}"] = response

        # Look for direct answers to questions
        for i, question in enumerate(pending_questions):
            # Extract key words from question
            question_words = re.findall(r'\b\w+\b', question.lower())
            
            # Look for answers that reference the question
            for word in question_words[:3]:  # Check first 3 key words
                if word in comment_body.lower():
                    # Extract the relevant part of the comment
                    sentences = re.split(r'[.!?]+', comment_body)
                    for sentence in sentences:
                        if word in sentence.lower():
                            responses[f"question_{i}"] = sentence.strip()
                            break

        return responses

    def detect_commands(self, comment_body: str) -> List[Dict[str, Any]]:
        """Detect agent commands in comments (retry, cancel, escalate, etc.)"""
        commands = []
        comment_lower = comment_body.lower()

        for command, patterns in self.command_patterns.items():
            for pattern in patterns:
                matches = re.finditer(pattern, comment_lower, re.MULTILINE)
                for match in matches:
                    commands.append({
                        'command': command,
                        'pattern': pattern,
                        'match_text': match.group(0),
                        'position': match.start(),
                        'confidence': self._calculate_command_confidence(command, match.group(0))
                    })

        # Sort by confidence and remove duplicates
        commands.sort(key=lambda x: x['confidence'], reverse=True)
        unique_commands = []
        seen_commands = set()
        
        for cmd in commands:
            if cmd['command'] not in seen_commands:
                unique_commands.append(cmd)
                seen_commands.add(cmd['command'])

        return unique_commands

    def extract_clarifications(self, comment_body: str, 
                             original_task: ParsedTask = None) -> Dict[str, Any]:
        """Extract clarifications and task modifications"""
        clarifications = {}

        # Look for file additions/modifications
        file_patterns = [
            r'(?:also\s+)?(?:include|add|check)\s+([a-zA-Z0-9_/\-\.]+\.(?:py|js|ts|md|yml|yaml|json|txt))',
            r'(?:file|path):\s*([a-zA-Z0-9_/\-\.]+)',
            r'`([a-zA-Z0-9_/\-\.]+\.(?:py|js|ts|md|yml|yaml|json|txt))`'
        ]
        
        mentioned_files = []
        for pattern in file_patterns:
            matches = re.finditer(pattern, comment_body, re.IGNORECASE)
            for match in matches:
                mentioned_files.append(match.group(1))
        
        if mentioned_files:
            clarifications['additional_files'] = mentioned_files

        # Look for requirement changes
        requirement_indicators = [
            r'(?:actually|instead|change|modify|update).*?(?:to|should|need)',
            r'(?:correction|mistake|wrong|error).*?(?:should|need)',
            r'(?:please|can you).*?(?:also|additionally|furthermore)'
        ]
        
        for pattern in requirement_indicators:
            matches = re.finditer(pattern, comment_body, re.IGNORECASE | re.DOTALL)
            for match in matches:
                clarifications['requirement_changes'] = match.group(0)
                break

        # Look for context additions
        context_indicators = [
            r'(?:background|context|information):\s*(.+)',
            r'(?:note that|keep in mind|important):\s*(.+)',
            r'(?:by the way|also|additionally):\s*(.+)'
        ]
        
        additional_context = []
        for pattern in context_indicators:
            matches = re.finditer(pattern, comment_body, re.IGNORECASE)
            for match in matches:
                additional_context.append(match.group(1).strip())
        
        if additional_context:
            clarifications['additional_context'] = additional_context

        # Look for priority changes
        priority_indicators = [
            r'(?:urgent|priority|important|critical|asap|quickly)',
            r'(?:low priority|not urgent|when you can|no rush)'
        ]
        
        for pattern in priority_indicators:
            if re.search(pattern, comment_body, re.IGNORECASE):
                clarifications['priority_change'] = 'high' if 'urgent' in pattern else 'low'
                break

        return clarifications

    def _determine_primary_intent(self, comment_body: str, 
                                commands: List[Dict[str, Any]]) -> Tuple[CommentIntent, float]:
        """Determine the primary intent of the comment"""
        
        # If commands were detected, use the highest confidence command
        if commands:
            primary_command = commands[0]['command']
            confidence = commands[0]['confidence']
            
            command_intent_map = {
                'cancel': CommentIntent.CANCEL,
                'retry': CommentIntent.RETRY,
                'escalate': CommentIntent.ESCALATE,
                'approve': CommentIntent.APPROVAL
            }
            
            if primary_command in command_intent_map:
                return command_intent_map[primary_command], confidence

        # Check for intent patterns
        comment_lower = comment_body.lower()
        
        for intent, patterns in self.intent_patterns.items():
            max_confidence = 0.0
            for pattern in patterns:
                if re.search(pattern, comment_lower, re.IGNORECASE):
                    confidence = self._calculate_pattern_confidence(pattern, comment_body)
                    max_confidence = max(max_confidence, confidence)
            
            if max_confidence > 0.5:
                return intent, max_confidence

        # Default to general comment
        return CommentIntent.GENERAL_COMMENT, 0.3

    def _analyze_sentiment(self, comment_body: str) -> SentimentType:
        """Analyze the sentiment of the comment"""
        comment_lower = comment_body.lower()
        
        sentiment_scores = {
            SentimentType.POSITIVE: 0,
            SentimentType.NEGATIVE: 0,
            SentimentType.NEUTRAL: 0,
            SentimentType.FRUSTRATED: 0,
            SentimentType.SATISFIED: 0
        }

        for sentiment, indicators in self.sentiment_indicators.items():
            for indicator in indicators:
                matches = len(re.findall(indicator, comment_lower))
                sentiment_scores[sentiment] += matches

        # Return the sentiment with the highest score
        max_sentiment = max(sentiment_scores, key=sentiment_scores.get)
        
        # If no clear sentiment, default to neutral
        if sentiment_scores[max_sentiment] == 0:
            return SentimentType.NEUTRAL
            
        return max_sentiment

    def _assess_urgency(self, comment_body: str) -> str:
        """Assess the urgency level of the comment"""
        comment_lower = comment_body.lower()
        
        urgency_score = 0
        
        for level, keywords in self.urgency_keywords.items():
            for keyword in keywords:
                if keyword in comment_lower:
                    if level == 'high':
                        urgency_score += 3
                    elif level == 'medium':
                        urgency_score += 2
                    else:
                        urgency_score += 1

        if urgency_score >= 5:
            return 'high'
        elif urgency_score >= 2:
            return 'medium'
        else:
            return 'low'

    def _extract_key_phrases(self, comment_body: str) -> List[str]:
        """Extract key phrases from the comment"""
        # Simple key phrase extraction
        phrases = []
        
        # Extract quoted text
        quoted_pattern = r'"([^"]+)"'
        quoted_matches = re.findall(quoted_pattern, comment_body)
        phrases.extend(quoted_matches)
        
        # Extract code snippets
        code_pattern = r'`([^`]+)`'
        code_matches = re.findall(code_pattern, comment_body)
        phrases.extend(code_matches)
        
        # Extract emphasized text (bold/italic)
        emphasis_patterns = [r'\*\*([^*]+)\*\*', r'__([^_]+)__', r'\*([^*]+)\*', r'_([^_]+)_']
        for pattern in emphasis_patterns:
            matches = re.findall(pattern, comment_body)
            phrases.extend(matches)

        return phrases[:10]  # Limit to 10 key phrases

    def _extract_file_mentions(self, comment_body: str) -> List[str]:
        """Extract file mentions from the comment"""
        file_patterns = [
            r'([a-zA-Z0-9_/\-\.]+\.(?:py|js|ts|jsx|tsx|md|yml|yaml|json|txt|html|css|scss|sql))',
            r'`([a-zA-Z0-9_/\-\.]+)`',
            r'src/[a-zA-Z0-9_/\-\.]+',
            r'docs/[a-zA-Z0-9_/\-\.]+',
            r'tests?/[a-zA-Z0-9_/\-\.]+'
        ]
        
        files = []
        for pattern in file_patterns:
            matches = re.findall(pattern, comment_body)
            files.extend(matches)
        
        # Remove duplicates and return
        return list(set(files))

    def _extract_user_mentions(self, comment_body: str) -> List[str]:
        """Extract @user mentions from the comment"""
        mention_pattern = r'@([a-zA-Z0-9_-]+)'
        mentions = re.findall(mention_pattern, comment_body)
        return mentions

    def _extract_questions(self, comment_body: str) -> List[str]:
        """Extract questions from the comment"""
        # Split into sentences and find those ending with ?
        sentences = re.split(r'[.!]+', comment_body)
        questions = []
        
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence.endswith('?'):
                questions.append(sentence)
            elif any(word in sentence.lower() for word in ['what', 'how', 'why', 'when', 'where', 'which', 'who']):
                # Likely a question even without ?
                questions.append(sentence + '?')
        
        return questions

    def _extract_action_items(self, comment_body: str) -> List[str]:
        """Extract action items from the comment"""
        action_patterns = [
            r'(?:please|can you|could you|would you)\s+([^.!?]+)',
            r'(?:need to|should|must|have to)\s+([^.!?]+)',
            r'(?:todo|to do|action|next step):\s*([^.!?]+)'
        ]
        
        actions = []
        for pattern in action_patterns:
            matches = re.findall(pattern, comment_body, re.IGNORECASE)
            actions.extend(matches)
        
        return [action.strip() for action in actions]

    def _calculate_command_confidence(self, command: str, match_text: str) -> float:
        """Calculate confidence score for command detection"""
        # Base confidence based on command clarity
        base_confidence = {
            'cancel': 0.9,
            'retry': 0.8,
            'escalate': 0.8,
            'approve': 0.7
        }.get(command, 0.5)
        
        # Adjust based on match context
        if match_text.startswith('/'):
            base_confidence += 0.1  # Explicit command syntax
        
        if len(match_text.split()) == 1:
            base_confidence += 0.05  # Single word commands are clearer
        
        return min(base_confidence, 1.0)

    def _calculate_pattern_confidence(self, pattern: str, text: str) -> float:
        """Calculate confidence for pattern matches"""
        # Simple confidence calculation based on pattern specificity
        base_confidence = 0.6
        
        # Longer patterns are more specific
        if len(pattern) > 20:
            base_confidence += 0.2
        
        # Patterns with word boundaries are more accurate
        if r'\b' in pattern:
            base_confidence += 0.1
        
        return min(base_confidence, 1.0)

    def _initialize_command_patterns(self) -> Dict[str, List[str]]:
        """Initialize command detection patterns"""
        return {
            'cancel': [
                r'/cancel',
                r'\bcancel\b',
                r'\bstop\b',
                r'\babort\b',
                r'cancel this',
                r'stop this',
                r'abort this'
            ],
            'retry': [
                r'/retry',
                r'\bretry\b',
                r'\btry again\b',
                r'retry this',
                r'try again',
                r'start over',
                r'restart'
            ],
            'escalate': [
                r'/escalate',
                r'\bescalate\b',
                r'human help',
                r'human review',
                r'escalate this',
                r'need human',
                r'get help'
            ],
            'approve': [
                r'/approve',
                r'\bapprove\b',
                r'\blgtm\b',
                r'looks good',
                r'sounds good',
                r'go ahead',
                r'proceed'
            ]
        }

    def _initialize_intent_patterns(self) -> Dict[CommentIntent, List[str]]:
        """Initialize intent detection patterns"""
        return {
            CommentIntent.FEEDBACK_RESPONSE: [
                r'\b(?:yes|no|option \d+|choice \d+|i choose|my answer)\b',
                r'^\d+\.?\s',  # Numbered responses
                r'\b(?:i think|i believe|i prefer|i would like)\b'
            ],
            CommentIntent.CLARIFICATION: [
                r'\b(?:also|additionally|furthermore|moreover)\b',
                r'\b(?:clarification|correction|mistake|wrong)\b',
                r'\b(?:actually|instead|change|modify)\b'
            ],
            CommentIntent.MODIFICATION_REQUEST: [
                r'\b(?:can you also|please also|could you|would you)\b',
                r'\b(?:modify|change|update|add|remove|include)\b',
                r'\b(?:different|alternative|another way)\b'
            ],
            CommentIntent.QUESTION: [
                r'\b(?:what|how|why|when|where|which|who)\b.*\?',
                r'\b(?:question|ask|wondering)\b',
                r'\?$'
            ]
        }

    def _initialize_sentiment_indicators(self) -> Dict[SentimentType, List[str]]:
        """Initialize sentiment analysis indicators"""
        return {
            SentimentType.POSITIVE: [
                r'\b(?:good|great|excellent|perfect|awesome|nice|cool)\b',
                r'\b(?:thank|thanks|appreciate|love|like)\b',
                r'\b(?:works|working|correct|right|exactly)\b'
            ],
            SentimentType.NEGATIVE: [
                r'\b(?:bad|terrible|awful|horrible|wrong|broken)\b',
                r'\b(?:hate|dislike|disappointed|frustrated)\b',
                r'\b(?:not work|doesn\'t work|failed|error)\b'
            ],
            SentimentType.FRUSTRATED: [
                r'\b(?:frustrated|annoyed|irritated|confused)\b',
                r'\b(?:why is|what\'s wrong|this is)\b.*\b(?:broken|not working)\b',
                r'!!+',  # Multiple exclamation marks
                r'\b(?:seriously|really|come on)\b'
            ],
            SentimentType.SATISFIED: [
                r'\b(?:satisfied|happy|pleased|content)\b',
                r'\b(?:perfect|exactly|just what|what i needed)\b',
                r'\b(?:solved|fixed|resolved|complete)\b'
            ]
        }

    def _initialize_urgency_keywords(self) -> Dict[str, List[str]]:
        """Initialize urgency assessment keywords"""
        return {
            'high': [
                'urgent', 'asap', 'immediately', 'critical', 'emergency',
                'quickly', 'fast', 'rush', 'priority', 'deadline'
            ],
            'medium': [
                'soon', 'important', 'needed', 'required', 'should',
                'when possible', 'relatively soon'
            ],
            'low': [
                'whenever', 'no rush', 'low priority', 'when you can',
                'eventually', 'at some point', 'not urgent'
            ]
        }