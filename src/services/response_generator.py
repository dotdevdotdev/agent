"""
Generates context-aware responses based on conversation history
"""

import structlog
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

from .conversation_manager import ConversationManager, ConversationTurn
from .agent_state_machine import AgentState
from .comment_analyzer import CommentAnalysis, SentimentType

logger = structlog.get_logger()


class ResponseGenerator:
    """Generates intelligent responses based on conversation context"""

    def __init__(self, conversation_manager: ConversationManager):
        self.conversation_manager = conversation_manager
        self.response_templates = self._initialize_response_templates()
        self.personalization_rules = self._initialize_personalization_rules()

    async def generate_progress_update(self, conversation_id: str, 
                                     current_state: AgentState,
                                     progress_details: Dict[str, Any]) -> str:
        """Generate contextual progress update"""
        try:
            # Get conversation context
            context = await self.conversation_manager.get_relevant_context(conversation_id, max_turns=5)
            preferences = await self.conversation_manager.extract_user_preferences(conversation_id)
            
            # Base progress message
            base_message = self._get_base_progress_message(current_state, progress_details)
            
            # Personalize based on preferences and context
            personalized_message = await self._personalize_message(
                base_message, preferences, context, "progress_update"
            )
            
            # Add contextual information
            contextual_message = await self._add_contextual_information(
                personalized_message, conversation_id, progress_details
            )
            
            logger.info(
                "Progress update generated",
                conversation_id=conversation_id,
                state=current_state.value,
                message_length=len(contextual_message)
            )
            
            return contextual_message
            
        except Exception as e:
            logger.error("Failed to generate progress update", error=str(e))
            return self._get_fallback_progress_message(current_state)

    async def generate_feedback_request(self, conversation_id: str,
                                      question: str, options: List[str] = None,
                                      urgency: str = "medium") -> str:
        """Generate personalized feedback request"""
        try:
            # Get conversation context
            context = await self.conversation_manager.get_relevant_context(conversation_id, max_turns=3)
            preferences = await self.conversation_manager.extract_user_preferences(conversation_id)
            
            # Build base request
            base_request = self._build_feedback_request(question, options, urgency)
            
            # Personalize based on communication style
            personalized_request = await self._personalize_message(
                base_request, preferences, context, "feedback_request"
            )
            
            # Add conversation-specific context
            contextual_request = await self._add_feedback_context(
                personalized_request, conversation_id, context
            )
            
            # Update pending questions
            await self.conversation_manager.update_pending_questions(
                conversation_id, [question] + (options or [])
            )
            
            logger.info(
                "Feedback request generated",
                conversation_id=conversation_id,
                urgency=urgency,
                has_options=bool(options)
            )
            
            return contextual_request
            
        except Exception as e:
            logger.error("Failed to generate feedback request", error=str(e))
            return f"❓ **Feedback Needed**\n\n{question}"

    async def generate_completion_summary(self, conversation_id: str,
                                        results: Dict[str, Any]) -> str:
        """Generate comprehensive completion summary"""
        try:
            # Get full conversation stats
            stats = await self.conversation_manager.get_conversation_stats(conversation_id)
            preferences = await self.conversation_manager.extract_user_preferences(conversation_id)
            
            # Build completion summary
            summary = await self._build_completion_summary(results, stats, preferences)
            
            # Add personalized closing
            personalized_summary = await self._add_personalized_closing(
                summary, conversation_id, preferences
            )
            
            logger.info(
                "Completion summary generated",
                conversation_id=conversation_id,
                result_keys=list(results.keys()),
                summary_length=len(personalized_summary)
            )
            
            return personalized_summary
            
        except Exception as e:
            logger.error("Failed to generate completion summary", error=str(e))
            return "✅ **Task Completed**\n\nYour task has been completed successfully."

    async def generate_error_explanation(self, conversation_id: str,
                                       error: Exception, recovery_options: List[str],
                                       error_context: Dict[str, Any] = None) -> str:
        """Generate helpful error explanation with recovery options"""
        try:
            # Get conversation context
            context = await self.conversation_manager.get_relevant_context(conversation_id, max_turns=3)
            preferences = await self.conversation_manager.extract_user_preferences(conversation_id)
            
            # Classify error type
            error_type = self._classify_error_type(error, error_context)
            
            # Build base error message
            base_message = self._build_error_message(error, error_type, recovery_options)
            
            # Personalize based on user's technical level and preferences
            personalized_message = await self._personalize_error_message(
                base_message, preferences, context, error_type
            )
            
            # Add conversation-specific context
            contextual_message = await self._add_error_context(
                personalized_message, conversation_id, error_context
            )
            
            logger.info(
                "Error explanation generated",
                conversation_id=conversation_id,
                error_type=error_type,
                recovery_options_count=len(recovery_options)
            )
            
            return contextual_message
            
        except Exception as e:
            logger.error("Failed to generate error explanation", error=str(e))
            return f"❌ **Error Occurred**\n\n{str(error)}\n\nPlease try again or contact support."

    async def generate_user_response_acknowledgment(self, conversation_id: str,
                                                  comment_analysis: CommentAnalysis) -> str:
        """Generate acknowledgment for user responses"""
        try:
            preferences = await self.conversation_manager.extract_user_preferences(conversation_id)
            
            # Build acknowledgment based on user's sentiment and intent
            acknowledgment = self._build_response_acknowledgment(comment_analysis, preferences)
            
            # Clear pending questions if they were answered
            if comment_analysis.intent.value in ['feedback_response', 'clarification']:
                await self.conversation_manager.clear_pending_questions(conversation_id)
            
            logger.info(
                "User response acknowledgment generated",
                conversation_id=conversation_id,
                intent=comment_analysis.intent.value,
                sentiment=comment_analysis.sentiment.value
            )
            
            return acknowledgment
            
        except Exception as e:
            logger.error("Failed to generate response acknowledgment", error=str(e))
            return "👍 Thanks for your response! I'll process this and continue."

    async def generate_escalation_message(self, conversation_id: str,
                                        escalation_reason: str,
                                        escalation_context: Dict[str, Any]) -> str:
        """Generate escalation message for human review"""
        try:
            # Get conversation summary
            summary = await self.conversation_manager.get_conversation_summary(conversation_id)
            stats = await self.conversation_manager.get_conversation_stats(conversation_id)
            
            # Build escalation message
            message = self._build_escalation_message(
                escalation_reason, escalation_context, summary, stats
            )
            
            logger.info(
                "Escalation message generated",
                conversation_id=conversation_id,
                reason=escalation_reason
            )
            
            return message
            
        except Exception as e:
            logger.error("Failed to generate escalation message", error=str(e))
            return f"🚨 **Escalated for Human Review**\n\nReason: {escalation_reason}"

    def _get_base_progress_message(self, state: AgentState, details: Dict[str, Any]) -> str:
        """Get base progress message for state"""
        templates = {
            AgentState.VALIDATING: "🔍 Validating your task requirements...",
            AgentState.ANALYZING: "🧠 Analyzing your request and planning the approach...",
            AgentState.IN_PROGRESS: "⚙️ Working on your task...",
            AgentState.IMPLEMENTING: "🛠️ Implementing the solution...",
            AgentState.TESTING: "🧪 Testing the implementation..."
        }
        
        base = templates.get(state, f"🤖 Current status: {state.value}")
        
        # Add specific details if available
        if details.get('current_step'):
            base += f"\n\nCurrent step: {details['current_step']}"
        
        if details.get('progress_percentage'):
            base += f"\nProgress: {details['progress_percentage']}%"
            
        return base

    async def _personalize_message(self, base_message: str, preferences: Dict[str, Any],
                                 context: List[ConversationTurn], message_type: str) -> str:
        """Personalize message based on user preferences"""
        
        # Communication style adjustment
        comm_style = preferences.get('communication_style', 'balanced')
        
        if comm_style == 'concise':
            # Make message more concise
            message = self._make_concise(base_message)
        elif comm_style == 'detailed':
            # Add more detail
            message = self._add_detail(base_message, message_type)
        else:
            message = base_message
        
        # Technical level adjustment
        if preferences.get('wants_explanations', False):
            message = self._add_explanations(message, message_type)
        
        # Urgency consideration
        urgency = preferences.get('typical_urgency', 'medium')
        if urgency == 'high':
            message = self._add_urgency_indicators(message)
        
        return message

    async def _add_contextual_information(self, message: str, conversation_id: str,
                                        details: Dict[str, Any]) -> str:
        """Add relevant contextual information"""
        
        # Add time estimates if available
        if details.get('estimated_completion'):
            eta = details['estimated_completion']
            message += f"\n\n⏱️ Estimated completion: {eta.strftime('%H:%M UTC')}"
        
        # Add file references if working on specific files
        if details.get('current_files'):
            files = details['current_files']
            if len(files) <= 3:
                message += f"\n\n📁 Working on: {', '.join(files)}"
            else:
                message += f"\n\n📁 Working on {len(files)} files"
        
        # Add next steps if available
        if details.get('next_steps'):
            steps = details['next_steps'][:2]  # Show max 2 next steps
            message += f"\n\n**Next steps:**"
            for step in steps:
                message += f"\n- {step}"
        
        return message

    def _build_feedback_request(self, question: str, options: List[str] = None,
                              urgency: str = "medium") -> str:
        """Build base feedback request"""
        urgency_indicators = {
            'low': "⏳",
            'medium': "❓", 
            'high': "🚨"
        }
        
        emoji = urgency_indicators.get(urgency, "❓")
        
        message = f"{emoji} **Feedback Needed**\n\n{question}"
        
        if options:
            message += "\n\n**Please choose one of the following:**"
            for i, option in enumerate(options, 1):
                message += f"\n{i}. {option}"
            message += "\n\n*You can reply with the number or text of your choice.*"
        
        return message

    async def _add_feedback_context(self, base_request: str, conversation_id: str,
                                  context: List[ConversationTurn]) -> str:
        """Add conversation-specific context to feedback request"""
        
        # Check if this is a repeated question
        recent_questions = [
            turn.content for turn in context 
            if turn.speaker == "agent" and "feedback" in turn.content.lower()
        ]
        
        if len(recent_questions) > 1:
            base_request += "\n\n*I noticed this is a follow-up question - thank you for your patience!*"
        
        # Add reference to previous context if relevant
        user_turns = [turn for turn in context if turn.speaker == "user"]
        if user_turns:
            last_user_input = user_turns[-1].content
            if len(last_user_input) > 100:  # Substantial previous input
                base_request += f"\n\n*Context: This relates to your previous request about {last_user_input[:50]}...*"
        
        return base_request

    async def _build_completion_summary(self, results: Dict[str, Any], 
                                      stats: Dict[str, Any],
                                      preferences: Dict[str, Any]) -> str:
        """Build comprehensive completion summary"""
        
        summary_parts = ["## ✅ Task Completed Successfully!"]
        
        # Add timing information
        if stats.get('duration'):
            duration = int(stats['duration'])
            if duration < 60:
                summary_parts.append(f"**Completion time**: {duration} seconds")
            elif duration < 3600:
                summary_parts.append(f"**Completion time**: {duration // 60} minutes")
            else:
                summary_parts.append(f"**Completion time**: {duration // 3600}h {(duration % 3600) // 60}m")
        
        # Add results summary
        if results.get('summary'):
            summary_parts.extend(["\n### Summary", results['summary']])
        
        # Add files modified
        if results.get('files_modified'):
            summary_parts.append("\n### Files Modified")
            for file_path in results['files_modified'][:10]:  # Limit to 10 files
                summary_parts.append(f"- `{file_path}`")
            
            if len(results['files_modified']) > 10:
                summary_parts.append(f"- ... and {len(results['files_modified']) - 10} more files")
        
        # Add key achievements
        if results.get('achievements'):
            summary_parts.append("\n### Key Achievements")
            for achievement in results['achievements']:
                summary_parts.append(f"- {achievement}")
        
        # Add output if available and user prefers details
        if results.get('output') and preferences.get('communication_style') == 'detailed':
            summary_parts.extend([
                "\n### Output",
                f"```\n{results['output'][:1000]}\n```"  # Limit output size
            ])
        
        return '\n'.join(summary_parts)

    async def _add_personalized_closing(self, summary: str, conversation_id: str,
                                      preferences: Dict[str, Any]) -> str:
        """Add personalized closing to completion summary"""
        
        # Get conversation stats for personalization
        stats = await self.conversation_manager.get_conversation_stats(conversation_id)
        
        closing_parts = []
        
        # Thank user for interaction
        if stats.get('user_turns', 0) > 3:
            closing_parts.append("Thank you for your clear communication throughout this task!")
        
        # Offer follow-up based on preferences
        if preferences.get('wants_explanations', False):
            closing_parts.append("Feel free to ask if you'd like me to explain any part of the implementation.")
        
        # Encourage future use
        closing_parts.append("Please feel free to create new tasks anytime!")
        
        if closing_parts:
            summary += "\n\n---\n" + " ".join(closing_parts)
        
        return summary

    def _build_error_message(self, error: Exception, error_type: str,
                           recovery_options: List[str]) -> str:
        """Build base error message"""
        
        error_emojis = {
            'validation': '⚠️',
            'processing': '❌',
            'timeout': '⏰',
            'permission': '🔒',
            'network': '🌐',
            'unknown': '❌'
        }
        
        emoji = error_emojis.get(error_type, '❌')
        
        message_parts = [
            f"{emoji} **Task Failed**",
            f"**Error Type**: {error_type.title()} Error",
            f"**Details**: {str(error)}"
        ]
        
        if recovery_options:
            message_parts.append("\n**Recovery Options:**")
            for i, option in enumerate(recovery_options, 1):
                message_parts.append(f"{i}. {option}")
        
        return '\n'.join(message_parts)

    async def _personalize_error_message(self, base_message: str, preferences: Dict[str, Any],
                                       context: List[ConversationTurn], error_type: str) -> str:
        """Personalize error message based on user preferences"""
        
        # Add technical details if user wants explanations
        if preferences.get('wants_explanations', False):
            base_message += "\n\n**What this means**: "
            explanations = {
                'validation': "The task request didn't meet the required format or was missing information.",
                'processing': "An error occurred while I was working on your task.",
                'timeout': "The task took longer than expected and timed out.",
                'permission': "I don't have the necessary permissions to complete this task.",
                'network': "There was a network connectivity issue."
            }
            base_message += explanations.get(error_type, "An unexpected error occurred.")
        
        # Adjust tone based on communication style
        comm_style = preferences.get('communication_style', 'balanced')
        if comm_style == 'concise':
            # Remove some verbosity
            base_message = base_message.replace('**What this means**: ', '')
        
        return base_message

    async def _add_error_context(self, message: str, conversation_id: str,
                               error_context: Dict[str, Any] = None) -> str:
        """Add conversation-specific error context"""
        
        if error_context:
            if error_context.get('retry_count', 0) > 0:
                message += f"\n\n*This was attempt #{error_context['retry_count'] + 1}*"
            
            if error_context.get('similar_errors'):
                message += "\n\n*Similar issues have occurred in this conversation - consider escalating.*"
        
        return message

    def _build_response_acknowledgment(self, analysis: CommentAnalysis,
                                     preferences: Dict[str, Any]) -> str:
        """Build acknowledgment for user responses"""
        
        # Base acknowledgment based on sentiment
        sentiment_responses = {
            SentimentType.POSITIVE: "👍 Great! Thanks for the positive feedback.",
            SentimentType.NEGATIVE: "I understand your concerns. Let me address them.",
            SentimentType.FRUSTRATED: "I can see you're frustrated. Let me help resolve this quickly.",
            SentimentType.SATISFIED: "Wonderful! I'm glad this is working well for you.",
            SentimentType.NEUTRAL: "Thanks for your response."
        }
        
        base = sentiment_responses.get(analysis.sentiment, "Thanks for your response.")
        
        # Add intent-specific acknowledgment
        if analysis.intent.value == 'feedback_response':
            base += " I've noted your feedback and will proceed accordingly."
        elif analysis.intent.value == 'clarification':
            base += " The clarification is helpful - I'll incorporate this into my approach."
        elif analysis.intent.value == 'modification_request':
            base += " I'll adjust the approach based on your request."
        
        # Add urgency acknowledgment if high urgency detected
        if analysis.urgency_level == 'high':
            base += " I'll prioritize this accordingly."
        
        return base

    def _build_escalation_message(self, reason: str, context: Dict[str, Any],
                                summary: str, stats: Dict[str, Any]) -> str:
        """Build escalation message for human review"""
        
        message_parts = [
            "🚨 **Task Escalated for Human Review**",
            f"**Escalation Reason**: {reason}",
            f"**Escalation Time**: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}"
        ]
        
        # Add context information
        if context.get('error_count'):
            message_parts.append(f"**Error Count**: {context['error_count']}")
        
        if context.get('retry_count'):
            message_parts.append(f"**Retry Attempts**: {context['retry_count']}")
        
        # Add conversation summary
        if summary and len(summary) > 20:
            message_parts.extend([
                "\n**Conversation Summary**:",
                summary
            ])
        
        # Add conversation stats
        if stats:
            message_parts.append(f"\n**Interaction Stats**: {stats.get('total_turns', 0)} exchanges over {stats.get('duration', 0):.0f} seconds")
        
        # Add next steps
        message_parts.extend([
            "\n**Next Steps**:",
            "- A human reviewer will examine this task within 24 hours",
            "- You may receive follow-up questions or requests for clarification",
            "- The task will be reassigned or modified based on the review",
            "\n*This issue will remain open pending human review.*"
        ])
        
        return '\n'.join(message_parts)

    def _classify_error_type(self, error: Exception, context: Dict[str, Any] = None) -> str:
        """Classify error type for better messaging"""
        error_str = str(error).lower()
        
        if 'validation' in error_str or 'invalid' in error_str:
            return 'validation'
        elif 'timeout' in error_str or 'time' in error_str:
            return 'timeout'
        elif 'permission' in error_str or 'access' in error_str or 'auth' in error_str:
            return 'permission'
        elif 'network' in error_str or 'connection' in error_str:
            return 'network'
        elif 'process' in error_str:
            return 'processing'
        else:
            return 'unknown'

    def _make_concise(self, message: str) -> str:
        """Make message more concise"""
        # Remove some verbose parts
        message = message.replace('**', '')  # Remove bold formatting
        message = message.replace('\n\n', '\n')  # Reduce line breaks
        return message

    def _add_detail(self, message: str, message_type: str) -> str:
        """Add more detail to message"""
        if message_type == 'progress_update':
            message += "\n\nI'll keep you updated on my progress."
        elif message_type == 'feedback_request':
            message += "\n\nTake your time to respond - I'll wait for your input."
        return message

    def _add_explanations(self, message: str, message_type: str) -> str:
        """Add explanations for users who want details"""
        explanations = {
            'progress_update': "\n\n*This update lets you know where I am in the process.*",
            'feedback_request': "\n\n*I need your input to proceed correctly.*"
        }
        return message + explanations.get(message_type, '')

    def _add_urgency_indicators(self, message: str) -> str:
        """Add urgency indicators for high-urgency users"""
        return "🔥 **Priority Update** 🔥\n\n" + message

    def _get_fallback_progress_message(self, state: AgentState) -> str:
        """Get fallback message if generation fails"""
        return f"🤖 Status update: {state.value}. Working on your request..."

    def _initialize_response_templates(self) -> Dict[str, Dict[str, str]]:
        """Initialize response templates"""
        return {
            'acknowledgments': {
                'positive': "👍 Thanks for the positive feedback!",
                'negative': "I understand your concerns.",
                'neutral': "Thanks for your response."
            },
            'progress_updates': {
                'starting': "🚀 Getting started on your task...",
                'working': "⚙️ Making progress on your request...",
                'testing': "🧪 Testing the solution...",
                'finishing': "🏁 Almost done!"
            }
        }

    def _initialize_personalization_rules(self) -> Dict[str, Any]:
        """Initialize personalization rules"""
        return {
            'communication_styles': {
                'concise': {
                    'max_length': 200,
                    'avoid_explanations': True,
                    'use_bullets': True
                },
                'detailed': {
                    'add_explanations': True,
                    'include_technical_details': True,
                    'use_examples': True
                }
            },
            'urgency_adaptations': {
                'high': {
                    'use_priority_indicators': True,
                    'shorter_updates': True,
                    'immediate_acknowledgment': True
                },
                'low': {
                    'relaxed_tone': True,
                    'detailed_explanations': True
                }
            }
        }