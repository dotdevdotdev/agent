# GitHub Labels for Agent Workflow

## Agent State Labels

| Label                     | Color     | Description                             | Next States                                                  |
| ------------------------- | --------- | --------------------------------------- | ------------------------------------------------------------ |
| `agent:queued`            | `#FFA500` | Task is waiting for agent to pick up    | `agent:in-progress`, `agent:failed`                          |
| `agent:in-progress`       | `#1E90FF` | Agent is actively working on the task   | `agent:awaiting-feedback`, `agent:completed`, `agent:failed` |
| `agent:awaiting-feedback` | `#9370DB` | Agent needs user input or clarification | `agent:in-progress`, `agent:completed`                       |
| `agent:completed`         | `#32CD32` | Task successfully completed by agent    | Final state                                                  |
| `agent:failed`            | `#DC143C` | Task failed or encountered error        | `agent:queued` (for retry)                                   |

## Priority Labels

| Label               | Color     | Description            |
| ------------------- | --------- | ---------------------- |
| `priority:low`      | `#90EE90` | Low priority task      |
| `priority:medium`   | `#FFD700` | Medium priority task   |
| `priority:high`     | `#FF6347` | High priority task     |
| `priority:critical` | `#FF0000` | Critical priority task |

## Task Type Labels

| Label                | Color     | Description                          |
| -------------------- | --------- | ------------------------------------ |
| `type:code-analysis` | `#E6E6FA` | Code analysis and review tasks       |
| `type:documentation` | `#F0E68C` | Documentation generation and updates |
| `type:refactoring`   | `#DDA0DD` | Code refactoring and optimization    |
| `type:research`      | `#98FB98` | Research and investigation tasks     |
| `type:bug-fix`       | `#FFB6C1` | Bug investigation and fixes          |
| `type:feature`       | `#87CEEB` | Feature implementation               |

## Label Management Commands

```bash
# Create all agent labels (run from repository root)
gh label create "agent:queued" --color "FFA500" --description "Task is queued for agent processing"
gh label create "agent:in-progress" --color "1E90FF" --description "Agent is actively working on this task"
gh label create "agent:awaiting-feedback" --color "9370DB" --description "Agent is waiting for user feedback"
gh label create "agent:completed" --color "32CD32" --description "Task completed successfully by agent"
gh label create "agent:failed" --color "DC143C" --description "Task failed or encountered an error"

gh label create "priority:low" --color "90EE90" --description "Low priority task"
gh label create "priority:medium" --color "FFD700" --description "Medium priority task"
gh label create "priority:high" --color "FF6347" --description "High priority task"
gh label create "priority:critical" --color "FF0000" --description "Critical priority task"

gh label create "type:code-analysis" --color "E6E6FA" --description "Code analysis and review"
gh label create "type:documentation" --color "F0E68C" --description "Documentation tasks"
gh label create "type:refactoring" --color "DDA0DD" --description "Code refactoring"
gh label create "type:research" --color "98FB98" --description "Research and investigation"
gh label create "type:bug-fix" --color "FFB6C1" --description "Bug fixes"
gh label create "type:feature" --color "87CEEB" --description "Feature implementation"
```

## State Machine Diagram

```
agent:queued
     ↓
agent:in-progress ← → agent:awaiting-feedback
     ↓                      ↓
agent:completed        agent:completed
     ↓                      ↓
[CLOSED]               [CLOSED]

Any state → agent:failed → agent:queued (retry)
```