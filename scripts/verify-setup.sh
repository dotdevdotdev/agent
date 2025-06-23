#!/bin/bash
# Verify Phase 1 implementation setup

set -e

echo "🔍 Verifying Phase 1 Implementation Setup..."

# Check required files exist
echo "📁 Checking required files..."
required_files=(
    ".github/ISSUE_TEMPLATE/agent-task.yml"
    ".github/workflows/agent-dispatcher.yml"
    "src/services/github_client.py"
    "docs/github-labels.md"
    "scripts/setup-github-labels.sh"
    "tests/test_github_client.py"
)

for file in "${required_files[@]}"; do
    if [ -f "$file" ]; then
        echo "✅ $file"
    else
        echo "❌ $file (missing)"
        exit 1
    fi
done

# Check Python syntax
echo "🐍 Checking Python syntax..."
python_files=(
    "src/services/github_client.py"
    "tests/test_github_client.py"
)

for file in "${python_files[@]}"; do
    if python3 -m py_compile "$file" 2>/dev/null; then
        echo "✅ $file (syntax OK)"
    else
        echo "❌ $file (syntax error)"
        exit 1
    fi
done

# Check YAML syntax
echo "📄 Checking YAML syntax..."
yaml_files=(
    ".github/ISSUE_TEMPLATE/agent-task.yml"
    ".github/workflows/agent-dispatcher.yml"
)

for file in "${yaml_files[@]}"; do
    if python3 -c "import yaml; yaml.safe_load(open('$file'))" 2>/dev/null; then
        echo "✅ $file (YAML syntax OK)"
    else
        echo "❌ $file (YAML syntax error)"
        exit 1
    fi
done

# Check script permissions
echo "🔒 Checking script permissions..."
scripts=(
    "scripts/setup-github-labels.sh"
    "scripts/start_server.sh"
)

for script in "${scripts[@]}"; do
    if [ -x "$script" ]; then
        echo "✅ $script (executable)"
    else
        echo "⚠️  $script (not executable - fixing)"
        chmod +x "$script"
        echo "✅ $script (made executable)"
    fi
done

# Check requirements.txt updated
echo "📦 Checking requirements.txt..."
if grep -q "aiofiles" requirements.txt; then
    echo "✅ aiofiles dependency added"
else
    echo "❌ aiofiles dependency missing"
    exit 1
fi

# Check GitHub CLI (optional)
echo "🐙 Checking GitHub CLI..."
if command -v gh &> /dev/null; then
    echo "✅ GitHub CLI installed"
    if gh auth status &> /dev/null; then
        echo "✅ GitHub CLI authenticated"
    else
        echo "⚠️  GitHub CLI not authenticated (run 'gh auth login')"
    fi
else
    echo "⚠️  GitHub CLI not installed (optional - needed for label setup)"
fi

echo ""
echo "🎉 Phase 1 Implementation Setup Verification Complete!"
echo ""
echo "📋 Next steps:"
echo "1. Configure repository secrets (AGENT_WEBHOOK_URL, AGENT_WEBHOOK_SECRET)"
echo "2. Run './scripts/setup-github-labels.sh' to create GitHub labels"
echo "3. Test issue creation with agent template"
echo "4. Deploy agent server and test webhook integration"