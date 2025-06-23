"""
Manages conversation state and context across multiple interactions
"""

import json
import structlog
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta

from .issue_parser import ParsedTask

logger = structlog.get_logger()


@dataclass
class ConversationTurn:
    timestamp: datetime
    speaker: str  # 'user' or 'agent'
    content: str
    intent: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    turn_id: str = field(default_factory=lambda: f"turn_{datetime.now().timestamp()}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConversationTurn':
        """Create from dictionary"""
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)


@dataclass
class ConversationContext:
    conversation_id: str
    issue_number: int
    repository: str
    current_task: Optional[Dict[str, Any]]  # Serialized ParsedTask
    turns: List[ConversationTurn] = field(default_factory=list)
    user_preferences: Dict[str, Any] = field(default_factory=dict)
    pending_questions: List[str] = field(default_factory=list)
    conversation_summary: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        data = asdict(self)
        data['turns'] = [turn.to_dict() for turn in self.turns]
        data['created_at'] = self.created_at.isoformat()
        data['updated_at'] = self.updated_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConversationContext':
        """Create from dictionary"""
        data['turns'] = [ConversationTurn.from_dict(turn) for turn in data.get('turns', [])]
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        data['updated_at'] = datetime.fromisoformat(data['updated_at'])
        return cls(**data)


class ConversationManager:
    """Manages conversation state and context"""

    def __init__(self, storage_backend=None):
        # In-memory storage for development (could be replaced with Redis/DB)
        self.conversations: Dict[str, ConversationContext] = {}
        self.storage = storage_backend
        
        # Conversation analysis settings
        self.max_turns_for_summary = 20
        self.summary_trigger_interval = 10  # Turns
        self.context_retention_days = 30

    async def start_conversation(self, repo_full_name: str, issue_number: int,
                               initial_task: ParsedTask = None) -> ConversationContext:
        """Start a new conversation context"""
        conversation_id = f"{repo_full_name}:{issue_number}"
        
        # Check if conversation already exists
        if conversation_id in self.conversations:
            existing = self.conversations[conversation_id]
            logger.info("Resuming existing conversation", conversation_id=conversation_id)
            return existing

        # Create new conversation
        context = ConversationContext(
            conversation_id=conversation_id,
            issue_number=issue_number,
            repository=repo_full_name,
            current_task=initial_task.__dict__ if initial_task else None
        )

        self.conversations[conversation_id] = context

        # Add initial turn if task provided
        if initial_task:
            await self.add_turn(
                conversation_id, 
                "user", 
                initial_task.prompt,
                intent="task_submission",
                context={
                    "task_type": initial_task.task_type,
                    "priority": initial_task.priority,
                    "files": initial_task.relevant_files
                }
            )

        logger.info(
            "Conversation started",
            conversation_id=conversation_id,
            repository=repo_full_name,
            issue=issue_number
        )

        return context

    async def add_turn(self, conversation_id: str, speaker: str, content: str,
                      intent: str = None, context: Dict = None) -> None:
        """Add a turn to the conversation"""
        if conversation_id not in self.conversations:
            logger.error("Conversation not found", conversation_id=conversation_id)
            return

        conversation = self.conversations[conversation_id]
        
        turn = ConversationTurn(
            timestamp=datetime.now(),
            speaker=speaker,
            content=content,
            intent=intent,
            context=context or {}
        )

        conversation.turns.append(turn)
        conversation.updated_at = datetime.now()

        # Update conversation summary if needed
        if len(conversation.turns) % self.summary_trigger_interval == 0:
            await self._update_conversation_summary(conversation_id)

        # Extract user preferences if this is a user turn
        if speaker == "user":
            await self._extract_and_update_preferences(conversation_id, content, context)

        logger.info(
            "Turn added to conversation",
            conversation_id=conversation_id,
            speaker=speaker,
            intent=intent,
            turn_count=len(conversation.turns)
        )

    async def get_conversation_summary(self, conversation_id: str) -> str:
        """Generate a summary of the conversation so far"""
        if conversation_id not in self.conversations:
            return "No conversation found"

        conversation = self.conversations[conversation_id]
        
        if conversation.conversation_summary:
            return conversation.conversation_summary

        # Generate summary from turns
        return await self._generate_summary_from_turns(conversation)

    async def extract_user_preferences(self, conversation_id: str) -> Dict[str, Any]:
        """Extract and update user preferences from conversation"""
        if conversation_id not in self.conversations:
            return {}

        conversation = self.conversations[conversation_id]
        return conversation.user_preferences

    async def get_relevant_context(self, conversation_id: str, 
                                 max_turns: int = 10) -> List[ConversationTurn]:
        """Get relevant conversation context for current interaction"""
        if conversation_id not in self.conversations:
            return []

        conversation = self.conversations[conversation_id]
        
        # Return the most recent turns
        recent_turns = conversation.turns[-max_turns:] if len(conversation.turns) > max_turns else conversation.turns
        
        # Filter out less relevant turns (system messages, etc.)
        relevant_turns = []
        for turn in recent_turns:
            if self._is_turn_relevant(turn):
                relevant_turns.append(turn)

        return relevant_turns

    async def update_pending_questions(self, conversation_id: str, questions: List[str]) -> None:
        """Update pending questions for the conversation"""
        if conversation_id not in self.conversations:
            return

        conversation = self.conversations[conversation_id]
        conversation.pending_questions = questions
        conversation.updated_at = datetime.now()

        logger.info(
            "Pending questions updated",
            conversation_id=conversation_id,
            question_count=len(questions)
        )

    async def clear_pending_questions(self, conversation_id: str) -> None:
        """Clear pending questions after they've been answered"""
        await self.update_pending_questions(conversation_id, [])

    async def get_conversation_stats(self, conversation_id: str) -> Dict[str, Any]:
        """Get statistics about the conversation"""
        if conversation_id not in self.conversations:
            return {}

        conversation = self.conversations[conversation_id]
        
        user_turns = [t for t in conversation.turns if t.speaker == "user"]
        agent_turns = [t for t in conversation.turns if t.speaker == "agent"]
        
        return {
            "total_turns": len(conversation.turns),
            "user_turns": len(user_turns),
            "agent_turns": len(agent_turns),
            "duration": (conversation.updated_at - conversation.created_at).total_seconds(),
            "pending_questions": len(conversation.pending_questions),
            "preferences_learned": len(conversation.user_preferences),
            "last_activity": conversation.updated_at.isoformat()
        }

    async def search_conversation_history(self, conversation_id: str, 
                                        query: str, limit: int = 5) -> List[ConversationTurn]:
        """Search through conversation history"""
        if conversation_id not in self.conversations:
            return []

        conversation = self.conversations[conversation_id]
        query_lower = query.lower()
        
        matching_turns = []
        for turn in conversation.turns:
            if query_lower in turn.content.lower():
                matching_turns.append(turn)
                if len(matching_turns) >= limit:
                    break

        return matching_turns

    async def export_conversation(self, conversation_id: str) -> Dict[str, Any]:
        """Export conversation for backup or analysis"""
        if conversation_id not in self.conversations:
            return {}

        conversation = self.conversations[conversation_id]
        return conversation.to_dict()

    async def import_conversation(self, conversation_data: Dict[str, Any]) -> str:
        """Import conversation from backup data"""
        try:
            conversation = ConversationContext.from_dict(conversation_data)
            self.conversations[conversation.conversation_id] = conversation
            
            logger.info(
                "Conversation imported",
                conversation_id=conversation.conversation_id,
                turn_count=len(conversation.turns)
            )
            
            return conversation.conversation_id
        except Exception as e:
            logger.error("Failed to import conversation", error=str(e))
            raise

    async def cleanup_old_conversations(self, days: int = None) -> int:
        """Clean up old conversations"""
        cutoff_days = days or self.context_retention_days
        cutoff_date = datetime.now() - timedelta(days=cutoff_days)
        
        conversations_to_remove = []
        for conv_id, conversation in self.conversations.items():
            if conversation.updated_at < cutoff_date:
                conversations_to_remove.append(conv_id)

        for conv_id in conversations_to_remove:
            del self.conversations[conv_id]

        logger.info(
            "Old conversations cleaned up",
            removed_count=len(conversations_to_remove),
            cutoff_days=cutoff_days
        )

        return len(conversations_to_remove)

    async def _update_conversation_summary(self, conversation_id: str) -> None:
        """Update the conversation summary"""
        if conversation_id not in self.conversations:
            return

        conversation = self.conversations[conversation_id]
        summary = await self._generate_summary_from_turns(conversation)
        conversation.conversation_summary = summary
        conversation.updated_at = datetime.now()

    async def _generate_summary_from_turns(self, conversation: ConversationContext) -> str:
        """Generate summary from conversation turns"""
        if not conversation.turns:
            return "No conversation yet"

        # Simple summary generation (could be enhanced with AI)
        summary_parts = []
        
        # Basic info
        user_turns = [t for t in conversation.turns if t.speaker == "user"]
        agent_turns = [t for t in conversation.turns if t.speaker == "agent"]
        
        summary_parts.append(f"Conversation with {len(conversation.turns)} total exchanges")
        summary_parts.append(f"User messages: {len(user_turns)}, Agent responses: {len(agent_turns)}")
        
        # Task info
        if conversation.current_task:
            task_type = conversation.current_task.get('task_type', 'Unknown')
            summary_parts.append(f"Task type: {task_type}")

        # Recent themes
        recent_turns = conversation.turns[-5:]  # Last 5 turns
        themes = self._extract_themes(recent_turns)
        if themes:
            summary_parts.append(f"Recent topics: {', '.join(themes)}")

        # Pending items
        if conversation.pending_questions:
            summary_parts.append(f"Pending questions: {len(conversation.pending_questions)}")

        return "; ".join(summary_parts)

    async def _extract_and_update_preferences(self, conversation_id: str, 
                                            content: str, context: Dict = None) -> None:
        """Extract user preferences from content and context"""
        conversation = self.conversations[conversation_id]
        
        # Simple preference extraction
        content_lower = content.lower()
        
        # Communication style preferences
        if any(word in content_lower for word in ['detailed', 'thorough', 'comprehensive']):
            conversation.user_preferences['communication_style'] = 'detailed'
        elif any(word in content_lower for word in ['brief', 'concise', 'short']):
            conversation.user_preferences['communication_style'] = 'concise'
        
        # Output format preferences
        if 'code' in content_lower and 'example' in content_lower:
            conversation.user_preferences['prefers_code_examples'] = True
        
        # Urgency patterns
        if any(word in content_lower for word in ['urgent', 'quickly', 'asap']):
            conversation.user_preferences['typical_urgency'] = 'high'
        elif any(word in content_lower for word in ['no rush', 'when possible']):
            conversation.user_preferences['typical_urgency'] = 'low'

        # Technical level
        if any(word in content_lower for word in ['explain', 'details', 'how', 'why']):
            conversation.user_preferences['wants_explanations'] = True

        conversation.updated_at = datetime.now()

    def _is_turn_relevant(self, turn: ConversationTurn) -> bool:
        """Determine if a turn is relevant for context"""
        # Filter out system messages, very short responses, etc.
        if len(turn.content.strip()) < 10:
            return False
        
        # Include user turns and substantial agent responses
        if turn.speaker == "user":
            return True
        
        if turn.speaker == "agent" and len(turn.content) > 50:
            return True
            
        return False

    def _extract_themes(self, turns: List[ConversationTurn]) -> List[str]:
        """Extract themes from recent turns"""
        themes = set()
        
        for turn in turns:
            content_lower = turn.content.lower()
            
            # Technical themes
            if any(word in content_lower for word in ['error', 'bug', 'issue']):
                themes.add('troubleshooting')
            if any(word in content_lower for word in ['implement', 'feature', 'add']):
                themes.add('implementation')
            if any(word in content_lower for word in ['test', 'testing', 'verify']):
                themes.add('testing')
            if any(word in content_lower for word in ['document', 'readme', 'docs']):
                themes.add('documentation')
            if any(word in content_lower for word in ['refactor', 'improve', 'optimize']):
                themes.add('optimization')

        return list(themes)