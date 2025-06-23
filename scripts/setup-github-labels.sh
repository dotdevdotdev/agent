#!/bin/bash
# Setup GitHub labels for agent workflow

set -e

echo "🏷️  Setting up GitHub labels for agent workflow..."

# Check if gh CLI is installed
if ! command -v gh &> /dev/null; then
    echo "❌ GitHub CLI (gh) is not installed. Please install it first."
    exit 1
fi

# Check if authenticated
if ! gh auth status &> /dev/null; then
    echo "❌ Not authenticated with GitHub. Please run 'gh auth login' first."
    exit 1
fi

# Create agent state labels
echo "Creating agent state labels..."
gh label create "agent:queued" --color "FFA500" --description "Task is queued for agent processing" --force
gh label create "agent:in-progress" --color "1E90FF" --description "Agent is actively working on this task" --force
gh label create "agent:awaiting-feedback" --color "9370DB" --description "Agent is waiting for user feedback" --force
gh label create "agent:completed" --color "32CD32" --description "Task completed successfully by agent" --force
gh label create "agent:failed" --color "DC143C" --description "Task failed or encountered an error" --force

# Create priority labels
echo "Creating priority labels..."
gh label create "priority:low" --color "90EE90" --description "Low priority task" --force
gh label create "priority:medium" --color "FFD700" --description "Medium priority task" --force
gh label create "priority:high" --color "FF6347" --description "High priority task" --force
gh label create "priority:critical" --color "FF0000" --description "Critical priority task" --force

# Create task type labels
echo "Creating task type labels..."
gh label create "type:code-analysis" --color "E6E6FA" --description "Code analysis and review" --force
gh label create "type:documentation" --color "F0E68C" --description "Documentation tasks" --force
gh label create "type:refactoring" --color "DDA0DD" --description "Code refactoring" --force
gh label create "type:research" --color "98FB98" --description "Research and investigation" --force
gh label create "type:bug-fix" --color "FFB6C1" --description "Bug fixes" --force
gh label create "type:feature" --color "87CEEB" --description "Feature implementation" --force

echo "✅ All labels created successfully!"
echo "📖 See docs/github-labels.md for usage information."