# Testing Mode Guide

## Overview

The system now supports a **Testing Mode** that allows issues with lower validation scores (minimum 25 instead of 50) to be processed. This is perfect for testing simple questions and development scenarios while maintaining security.

## How to Enable Testing Mode

Add any of these indicators to your GitHub issue **title** or **body**:

### Option 1: In Issue Title
```
[TEST] Can you explain how authentication works?
[TESTING] Quick question about the API
[DEV] Simple test task
```

### Option 2: In Issue Body
```markdown
### Detailed Prompt
This is a simple test question. [testing mode]

What does the login function do?
```

### Option 3: Explicit Keywords
- `testing mode`
- `test mode` 
- `allow low validation`
- `[development]`

## What Testing Mode Does

### ✅ **Allows:**
- **Lower validation scores** (25+ instead of 50+)
- **Simple questions** without full template completion
- **Incomplete context** for quick tests
- **Missing file references** for general questions
- **Security warnings** (passwords/secrets) for educational examples

### ❌ **Still Blocks:**
- **Critical validation errors** (malformed requests)
- **Completely empty prompts**
- **Actual security issues** in production contexts

## Example Usage

### Regular Issue (Requires Score 50+)
```markdown
### Task Type
Code Analysis

### Detailed Prompt
Please analyze the performance issues in our authentication system and provide optimization recommendations with detailed benchmarks and implementation steps.

### Relevant Files or URLs  
src/auth.py, src/middleware.py, tests/test_auth.py

### Additional Context
This is for our production system handling 10k+ users daily. We've noticed 2-3 second login delays during peak hours.

✅ Score: 75/100 → ✅ Processes normally
```

### Testing Mode Issue (Requires Score 25+)
```markdown
[TEST] Quick question about authentication

### Detailed Prompt
How does the login function work?

🧪 Score: 30/100 → ✅ Processes in testing mode
```

## GitHub Feedback

When testing mode is active, you'll see:

```markdown
🧪 **Testing Mode Active** - Reduced validation requirements applied
✅ **Task Validation Successful**
Your task has been validated with a completeness score of 35/100.

⚠️ **Warnings:**
- ⚠️ Testing mode enabled - reduced validation requirements
```

## Security in Testing Mode

Testing mode is **secure by design**:

- ✅ **Educational examples** with fake passwords/secrets are allowed
- ✅ **Development questions** about security concepts are allowed  
- ❌ **Actual credentials** or real secrets are still flagged
- ❌ **Production security issues** are still blocked

## Best Practices

### ✅ **Good for Testing:**
```markdown
[TEST] How does JWT authentication work?
[DEV] Explain the password hashing function
[TESTING] What's the difference between OAuth and SAML?
```

### ❌ **Still Use Full Template For:**
- Production code analysis
- Complex feature implementations  
- Security-sensitive tasks
- Detailed refactoring requests

## Disabling Testing Mode

Simply remove the testing indicators from your issue title/body:
- Remove `[TEST]`, `[TESTING]`, `[DEV]` tags
- Remove phrases like "testing mode" 
- The system will revert to normal validation (50+ score required)

## API Integration

For programmatic access, the testing mode status is available:

```python
# Parse issue
parsed_task = issue_parser.parse_issue(issue_body, issue_title)
print(f"Testing mode: {parsed_task.testing_mode}")

# Validate with testing mode support
validation_result = task_validator.validate_task_completeness(parsed_task)
ready = task_validator.is_ready_for_processing(parsed_task)
```

This enables flexible testing while maintaining production security standards! 🧪✅