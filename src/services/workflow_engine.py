"""
Configurable workflow engine for task processing pipelines
"""

import asyncio
import structlog
from typing import Dict, List, Optional, Any, Callable, Type, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
import importlib
import inspect

from src.models.configuration import (
    WorkflowConfig, WorkflowConfigCreate, ProcessingStep, ValidationRule,
    WorkflowStage, Repository, AgentConfig
)
from src.models.jobs import JobStatus
from src.services.database_service import DatabaseService
from src.services.issue_parser import ParsedTask, TaskType

logger = structlog.get_logger()


class StepStatus(str, Enum):
    """Processing step status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    RETRYING = "retrying"


class ConditionType(str, Enum):
    """Available condition types"""
    TASK_COMPLEXITY = "task_complexity"
    TASK_TYPE = "task_type"
    FILE_COUNT = "file_count"
    USER_ROLE = "user_role"
    REPOSITORY_SIZE = "repository_size"
    HAS_CODE_CHANGES = "has_code_changes"
    AGENT_CAPABILITY = "agent_capability"
    CUSTOM_SCRIPT = "custom_script"


@dataclass
class StepContext:
    """Context for step execution"""
    job_id: str
    repository: Repository
    agent_config: AgentConfig
    parsed_task: ParsedTask
    workflow_config: WorkflowConfig
    previous_results: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    step_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StepResult:
    """Result of step execution"""
    step_name: str
    status: StepStatus
    output: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0
    next_steps: List[str] = field(default_factory=list)


@dataclass
class WorkflowExecution:
    """Workflow execution tracking"""
    job_id: str
    workflow_id: str
    status: JobStatus = JobStatus.PENDING
    current_step: Optional[str] = None
    step_results: Dict[str, StepResult] = field(default_factory=dict)
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    context: Optional[StepContext] = None


# Base processor interface
class BaseProcessor:
    """Base class for workflow step processors"""
    
    def __init__(self, step_config: ProcessingStep):
        self.step_config = step_config
        self.name = step_config.name
        self.stage = step_config.stage
        self.parameters = step_config.parameters

    async def execute(self, context: StepContext) -> StepResult:
        """Execute the processing step"""
        raise NotImplementedError("Subclasses must implement execute method")

    async def validate_inputs(self, context: StepContext) -> bool:
        """Validate that required inputs are available"""
        return True

    async def should_skip(self, context: StepContext) -> Tuple[bool, str]:
        """Check if this step should be skipped"""
        return False, ""


# Built-in processors
class ValidationProcessor(BaseProcessor):
    """Validates parsed task using configured rules"""

    async def execute(self, context: StepContext) -> StepResult:
        start_time = datetime.utcnow()
        
        try:
            validation_rules = context.workflow_config.validation_rules
            task = context.parsed_task
            
            validation_result = {
                'is_valid': True,
                'score': 0,
                'errors': [],
                'warnings': []
            }
            
            # Apply validation rules
            for rule in validation_rules:
                rule_result = await self._apply_validation_rule(rule, task, context)
                validation_result['score'] += rule_result.get('score', 0)
                
                if rule_result.get('errors'):
                    validation_result['errors'].extend(rule_result['errors'])
                    if rule.severity == 'error':
                        validation_result['is_valid'] = False
                
                if rule_result.get('warnings'):
                    validation_result['warnings'].extend(rule_result['warnings'])
            
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            
            return StepResult(
                step_name=self.name,
                status=StepStatus.COMPLETED,
                output=validation_result,
                metadata={
                    'rules_applied': len(validation_rules),
                    'validation_score': validation_result['score']
                },
                execution_time=execution_time
            )
            
        except Exception as e:
            logger.error("Validation step failed", step=self.name, error=str(e))
            return StepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error=str(e),
                execution_time=(datetime.utcnow() - start_time).total_seconds()
            )

    async def _apply_validation_rule(self, rule: ValidationRule, task: ParsedTask, 
                                   context: StepContext) -> Dict[str, Any]:
        """Apply a single validation rule"""
        result = {'score': 0, 'errors': [], 'warnings': []}
        
        if rule.rule_type == 'length':
            min_length = rule.parameters.get('min_length', 0)
            field = rule.parameters.get('field', 'prompt')
            value = getattr(task, field, '')
            
            if len(value) < min_length:
                message = rule.error_message.format(field=field, min_length=min_length, actual_length=len(value))
                if rule.severity == 'error':
                    result['errors'].append(message)
                else:
                    result['warnings'].append(message)
            else:
                result['score'] += rule.parameters.get('score', 10)
        
        elif rule.rule_type == 'required':
            field = rule.parameters.get('field')
            value = getattr(task, field, None)
            
            if not value:
                message = rule.error_message.format(field=field)
                if rule.severity == 'error':
                    result['errors'].append(message)
                else:
                    result['warnings'].append(message)
            else:
                result['score'] += rule.parameters.get('score', 5)
        
        elif rule.rule_type == 'pattern':
            import re
            field = rule.parameters.get('field', 'prompt')
            pattern = rule.parameters.get('pattern')
            value = getattr(task, field, '')
            
            if pattern and not re.search(pattern, value):
                message = rule.error_message.format(field=field, pattern=pattern)
                if rule.severity == 'error':
                    result['errors'].append(message)
                else:
                    result['warnings'].append(message)
            else:
                result['score'] += rule.parameters.get('score', 5)
        
        return result


class AnalysisProcessor(BaseProcessor):
    """Analyzes task and repository context"""

    async def execute(self, context: StepContext) -> StepResult:
        start_time = datetime.utcnow()
        
        try:
            analysis_result = {
                'task_complexity': await self._analyze_task_complexity(context),
                'repository_info': await self._analyze_repository(context),
                'required_capabilities': await self._identify_capabilities(context),
                'estimated_time': await self._estimate_processing_time(context)
            }
            
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            
            return StepResult(
                step_name=self.name,
                status=StepStatus.COMPLETED,
                output=analysis_result,
                metadata={
                    'complexity': analysis_result['task_complexity'],
                    'estimated_time': analysis_result['estimated_time']
                },
                execution_time=execution_time
            )
            
        except Exception as e:
            logger.error("Analysis step failed", step=self.name, error=str(e))
            return StepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error=str(e),
                execution_time=(datetime.utcnow() - start_time).total_seconds()
            )

    async def _analyze_task_complexity(self, context: StepContext) -> str:
        """Analyze task complexity"""
        task = context.parsed_task
        complexity_score = 0
        
        # Factor in task type
        complex_types = [TaskType.FEATURE_IMPLEMENTATION, TaskType.REFACTORING]
        if task.task_type in complex_types:
            complexity_score += 3
        
        # Factor in prompt length
        if len(task.prompt) > 500:
            complexity_score += 2
        elif len(task.prompt) > 200:
            complexity_score += 1
        
        # Factor in file count
        if len(task.relevant_files) > 5:
            complexity_score += 2
        elif len(task.relevant_files) > 1:
            complexity_score += 1
        
        if complexity_score >= 6:
            return "complex"
        elif complexity_score >= 3:
            return "medium"
        else:
            return "simple"

    async def _analyze_repository(self, context: StepContext) -> Dict[str, Any]:
        """Analyze repository characteristics"""
        repo = context.repository
        return {
            'name': repo.full_name,
            'description': repo.description,
            'settings': repo.settings,
            'estimated_size': 'medium'  # Would analyze actual repo
        }

    async def _identify_capabilities(self, context: StepContext) -> List[str]:
        """Identify required agent capabilities"""
        task = context.parsed_task
        required_caps = []
        
        if task.task_type == TaskType.CODE_ANALYSIS:
            required_caps.extend(['code_analysis', 'documentation'])
        elif task.task_type == TaskType.BUG_INVESTIGATION:
            required_caps.extend(['debugging', 'testing', 'code_analysis'])
        elif task.task_type == TaskType.FEATURE_IMPLEMENTATION:
            required_caps.extend(['code_generation', 'testing', 'documentation'])
        elif task.task_type == TaskType.REFACTORING:
            required_caps.extend(['refactoring', 'code_analysis', 'testing'])
        
        return required_caps

    async def _estimate_processing_time(self, context: StepContext) -> int:
        """Estimate processing time in seconds"""
        task = context.parsed_task
        base_time = 60  # 1 minute base
        
        if task.task_type in [TaskType.FEATURE_IMPLEMENTATION, TaskType.REFACTORING]:
            base_time *= 5
        elif task.task_type in [TaskType.CODE_ANALYSIS, TaskType.BUG_INVESTIGATION]:
            base_time *= 2
        
        # Add time for file processing
        base_time += len(task.relevant_files) * 30
        
        return base_time


class ConditionalProcessor(BaseProcessor):
    """Handles conditional workflow branching"""

    async def execute(self, context: StepContext) -> StepResult:
        start_time = datetime.utcnow()
        
        try:
            conditions = self.step_config.conditions
            next_steps = []
            
            for condition_name, condition_config in conditions.items():
                if await self._evaluate_condition(condition_config, context):
                    next_steps.extend(condition_config.get('then_steps', []))
                else:
                    next_steps.extend(condition_config.get('else_steps', []))
            
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            
            return StepResult(
                step_name=self.name,
                status=StepStatus.COMPLETED,
                output={'conditions_evaluated': list(conditions.keys())},
                next_steps=next_steps,
                execution_time=execution_time
            )
            
        except Exception as e:
            logger.error("Conditional step failed", step=self.name, error=str(e))
            return StepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error=str(e),
                execution_time=(datetime.utcnow() - start_time).total_seconds()
            )

    async def _evaluate_condition(self, condition_config: Dict[str, Any], 
                                context: StepContext) -> bool:
        """Evaluate a single condition"""
        condition_type = condition_config.get('type')
        
        if condition_type == ConditionType.TASK_COMPLEXITY.value:
            required_complexity = condition_config.get('value')
            analysis_result = context.previous_results.get('analysis', {})
            task_complexity = analysis_result.get('task_complexity', 'simple')
            return task_complexity == required_complexity
        
        elif condition_type == ConditionType.TASK_TYPE.value:
            required_types = condition_config.get('value', [])
            if isinstance(required_types, str):
                required_types = [required_types]
            return context.parsed_task.task_type.value in required_types
        
        elif condition_type == ConditionType.FILE_COUNT.value:
            operator = condition_config.get('operator', 'gt')
            threshold = condition_config.get('value', 0)
            file_count = len(context.parsed_task.relevant_files)
            
            if operator == 'gt':
                return file_count > threshold
            elif operator == 'lt':
                return file_count < threshold
            elif operator == 'eq':
                return file_count == threshold
        
        elif condition_type == ConditionType.AGENT_CAPABILITY.value:
            required_capability = condition_config.get('value')
            agent_capabilities = [cap.value for cap in context.agent_config.capabilities]
            return required_capability in agent_capabilities
        
        return False


class WorkflowEngine:
    """Manages configurable workflow execution"""

    def __init__(self, db_service: DatabaseService):
        self.db = db_service
        self.processors = self._initialize_processors()
        self.active_executions: Dict[str, WorkflowExecution] = {}
        self.default_workflows = self._create_default_workflows()

    def _initialize_processors(self) -> Dict[str, Type[BaseProcessor]]:
        """Initialize available processors"""
        return {
            'validation': ValidationProcessor,
            'analysis': AnalysisProcessor,
            'conditional': ConditionalProcessor,
            # Additional processors would be registered here
        }

    def _create_default_workflows(self) -> Dict[str, WorkflowConfig]:
        """Create default workflow configurations"""
        return {
            'standard': WorkflowConfig(
                id='default_standard',
                organization_id='',
                name='Standard Processing',
                description='Standard workflow for most tasks',
                task_types=[task_type.value for task_type in TaskType],
                validation_rules=[
                    ValidationRule(
                        name='prompt_length',
                        rule_type='length',
                        parameters={'field': 'prompt', 'min_length': 10, 'score': 10},
                        error_message='Prompt must be at least {min_length} characters (got {actual_length})',
                        severity='warning'
                    ),
                    ValidationRule(
                        name='required_prompt',
                        rule_type='required',
                        parameters={'field': 'prompt', 'score': 20},
                        error_message='Prompt is required',
                        severity='error'
                    )
                ],
                processing_steps=[
                    ProcessingStep(
                        name='validation',
                        stage=WorkflowStage.VALIDATION,
                        processor_class='validation',
                        parameters={},
                        timeout_seconds=30
                    ),
                    ProcessingStep(
                        name='analysis',
                        stage=WorkflowStage.ANALYSIS,
                        processor_class='analysis',
                        parameters={},
                        depends_on=['validation'],
                        timeout_seconds=60
                    ),
                    ProcessingStep(
                        name='routing',
                        stage=WorkflowStage.ANALYSIS,
                        processor_class='conditional',
                        parameters={},
                        conditions={
                            'complexity_check': {
                                'type': 'task_complexity',
                                'value': 'simple',
                                'then_steps': ['simple_implementation'],
                                'else_steps': ['complex_implementation']
                            }
                        },
                        depends_on=['analysis']
                    )
                ],
                is_default=True,
                is_active=True
            )
        }

    async def create_workflow_config(self, org_id: str, workflow: WorkflowConfigCreate,
                                   created_by: str) -> WorkflowConfig:
        """Create new workflow configuration"""
        
        # Validate processing steps
        await self._validate_workflow_config(workflow)
        
        config = WorkflowConfig(
            **workflow.dict(),
            organization_id=org_id,
            created_by=created_by,
            updated_by=created_by
        )
        
        # Store in database
        if self.db.pool:
            async with self.db.get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO workflow_configs (id, organization_id, name, description,
                                                task_types, validation_rules, processing_steps,
                                                state_config, error_handling, settings,
                                                created_by, updated_by)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    """,
                    config.id, config.organization_id, config.name, config.description,
                    config.task_types, 
                    [rule.dict() for rule in config.validation_rules],
                    [step.dict() for step in config.processing_steps],
                    config.state_config, config.error_handling, config.settings,
                    config.created_by, config.updated_by
                )
        else:
            self.db._memory_storage['workflow_configs'][config.id] = config.dict()
        
        logger.info("Workflow configuration created", config_id=config.id, name=config.name)
        return config

    async def get_workflow_config(self, workflow_id: str) -> Optional[WorkflowConfig]:
        """Get workflow configuration by ID"""
        # Check defaults first
        if workflow_id in self.default_workflows:
            return self.default_workflows[workflow_id]
        
        # Check database
        if self.db.pool:
            async with self.db.get_connection() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM workflow_configs WHERE id = $1 AND is_active = true",
                    workflow_id
                )
                if row:
                    data = dict(row)
                    # Convert JSON fields back to objects
                    data['validation_rules'] = [ValidationRule(**rule) for rule in data['validation_rules']]
                    data['processing_steps'] = [ProcessingStep(**step) for step in data['processing_steps']]
                    return WorkflowConfig(**data)
        else:
            config_data = self.db._memory_storage['workflow_configs'].get(workflow_id)
            if config_data:
                return WorkflowConfig(**config_data)
        
        return None

    async def get_workflow_for_task(self, repository_id: str, task_type: str) -> Optional[WorkflowConfig]:
        """Get appropriate workflow for task type"""
        repository = await self.db.get_repository(repository_id)
        if not repository:
            return None
        
        # Check if repository has specific workflow configured
        if repository.workflow_config_id:
            workflow = await self.get_workflow_config(repository.workflow_config_id)
            if workflow and (not workflow.task_types or task_type in workflow.task_types):
                return workflow
        
        # Get organization default workflow
        org_workflows = await self.list_workflow_configs(repository.organization_id)
        for workflow in org_workflows:
            if workflow.is_default and (not workflow.task_types or task_type in workflow.task_types):
                return workflow
        
        # Fallback to system default
        return self.default_workflows['standard']

    async def list_workflow_configs(self, org_id: str) -> List[WorkflowConfig]:
        """List workflow configurations for organization"""
        configs = []
        
        if self.db.pool:
            async with self.db.get_connection() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM workflow_configs 
                    WHERE organization_id = $1 AND is_active = true
                    ORDER BY is_default DESC, name ASC
                    """,
                    org_id
                )
                for row in rows:
                    data = dict(row)
                    data['validation_rules'] = [ValidationRule(**rule) for rule in data['validation_rules']]
                    data['processing_steps'] = [ProcessingStep(**step) for step in data['processing_steps']]
                    configs.append(WorkflowConfig(**data))
        else:
            for config_data in self.db._memory_storage['workflow_configs'].values():
                if config_data['organization_id'] == org_id and config_data.get('is_active', True):
                    configs.append(WorkflowConfig(**config_data))
        
        return configs

    async def execute_workflow(self, workflow_id: str, job_id: str, repository: Repository,
                             agent_config: AgentConfig, parsed_task: ParsedTask,
                             progress_callback: Optional[Callable[[str, int], None]] = None) -> WorkflowExecution:
        """Execute workflow for task"""
        workflow_config = await self.get_workflow_config(workflow_id)
        if not workflow_config:
            raise ValueError(f"Workflow configuration not found: {workflow_id}")
        
        # Create execution context
        context = StepContext(
            job_id=job_id,
            repository=repository,
            agent_config=agent_config,
            parsed_task=parsed_task,
            workflow_config=workflow_config
        )
        
        # Create execution tracker
        execution = WorkflowExecution(
            job_id=job_id,
            workflow_id=workflow_id,
            status=JobStatus.RUNNING,
            context=context
        )
        
        self.active_executions[job_id] = execution
        
        try:
            await self._execute_workflow_steps(execution, progress_callback)
            execution.status = JobStatus.COMPLETED
            execution.completed_at = datetime.utcnow()
            
        except Exception as e:
            logger.error("Workflow execution failed", job_id=job_id, error=str(e))
            execution.status = JobStatus.FAILED
            execution.completed_at = datetime.utcnow()
            raise
        
        finally:
            # Clean up active execution
            if job_id in self.active_executions:
                del self.active_executions[job_id]
        
        logger.info(
            "Workflow execution completed",
            job_id=job_id,
            workflow_id=workflow_id,
            status=execution.status,
            steps_completed=len(execution.step_results)
        )
        
        return execution

    async def _execute_workflow_steps(self, execution: WorkflowExecution,
                                    progress_callback: Optional[Callable[[str, int], None]] = None):
        """Execute workflow steps in order"""
        workflow_config = execution.context.workflow_config
        steps = workflow_config.processing_steps
        
        # Build dependency graph
        dependency_graph = self._build_dependency_graph(steps)
        completed_steps = set()
        total_steps = len(steps)
        
        while len(completed_steps) < total_steps:
            # Find steps ready to execute
            ready_steps = []
            for step in steps:
                if step.name not in completed_steps and step.name not in [r.step_name for r in execution.step_results.values()]:
                    dependencies_met = all(dep in completed_steps for dep in step.depends_on)
                    if dependencies_met:
                        ready_steps.append(step)
            
            if not ready_steps:
                break  # No more steps can be executed
            
            # Execute ready steps
            for step in ready_steps:
                execution.current_step = step.name
                
                if progress_callback:
                    progress = int((len(completed_steps) / total_steps) * 100)
                    progress_callback(f"Executing step: {step.name}", progress)
                
                result = await self._execute_step(step, execution.context)
                execution.step_results[step.name] = result
                
                if result.status == StepStatus.COMPLETED:
                    completed_steps.add(step.name)
                    # Update context with results
                    execution.context.previous_results[step.name] = result.output
                elif result.status == StepStatus.FAILED:
                    if not step.is_optional:
                        raise Exception(f"Required step {step.name} failed: {result.error}")
                    else:
                        completed_steps.add(step.name)  # Skip optional failed steps

    async def _execute_step(self, step: ProcessingStep, context: StepContext) -> StepResult:
        """Execute a single workflow step"""
        processor_class = self.processors.get(step.processor_class)
        if not processor_class:
            return StepResult(
                step_name=step.name,
                status=StepStatus.FAILED,
                error=f"Unknown processor class: {step.processor_class}"
            )
        
        processor = processor_class(step)
        
        # Check if step should be skipped
        should_skip, skip_reason = await processor.should_skip(context)
        if should_skip:
            return StepResult(
                step_name=step.name,
                status=StepStatus.SKIPPED,
                metadata={'skip_reason': skip_reason}
            )
        
        # Validate inputs
        if not await processor.validate_inputs(context):
            return StepResult(
                step_name=step.name,
                status=StepStatus.FAILED,
                error="Input validation failed"
            )
        
        # Execute with timeout
        try:
            if step.timeout_seconds:
                result = await asyncio.wait_for(
                    processor.execute(context),
                    timeout=step.timeout_seconds
                )
            else:
                result = await processor.execute(context)
            
            logger.info(
                "Workflow step completed",
                step=step.name,
                status=result.status,
                execution_time=result.execution_time
            )
            
            return result
            
        except asyncio.TimeoutError:
            return StepResult(
                step_name=step.name,
                status=StepStatus.FAILED,
                error=f"Step timed out after {step.timeout_seconds} seconds"
            )
        except Exception as e:
            logger.error("Step execution failed", step=step.name, error=str(e))
            return StepResult(
                step_name=step.name,
                status=StepStatus.FAILED,
                error=str(e)
            )

    def _build_dependency_graph(self, steps: List[ProcessingStep]) -> Dict[str, List[str]]:
        """Build step dependency graph"""
        graph = {}
        for step in steps:
            graph[step.name] = step.depends_on
        return graph

    async def _validate_workflow_config(self, workflow: WorkflowConfigCreate):
        """Validate workflow configuration"""
        # Check for circular dependencies
        step_names = {step.name for step in workflow.processing_steps}
        
        for step in workflow.processing_steps:
            if step.processor_class not in self.processors:
                raise ValueError(f"Unknown processor class: {step.processor_class}")
            
            for dep in step.depends_on:
                if dep not in step_names:
                    raise ValueError(f"Step {step.name} depends on unknown step: {dep}")
        
        # Check for circular dependencies (simplified check)
        # A more comprehensive check would use topological sorting

    async def cancel_workflow(self, job_id: str) -> bool:
        """Cancel active workflow execution"""
        if job_id in self.active_executions:
            execution = self.active_executions[job_id]
            execution.status = JobStatus.CANCELLED
            execution.completed_at = datetime.utcnow()
            del self.active_executions[job_id]
            
            logger.info("Workflow execution cancelled", job_id=job_id)
            return True
        
        return False

    async def get_execution_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get current execution status"""
        if job_id in self.active_executions:
            execution = self.active_executions[job_id]
            return {
                'job_id': job_id,
                'workflow_id': execution.workflow_id,
                'status': execution.status.value,
                'current_step': execution.current_step,
                'completed_steps': len(execution.step_results),
                'total_steps': len(execution.context.workflow_config.processing_steps),
                'started_at': execution.started_at.isoformat(),
                'step_results': {
                    name: {
                        'status': result.status.value,
                        'execution_time': result.execution_time
                    }
                    for name, result in execution.step_results.items()
                }
            }
        
        return None