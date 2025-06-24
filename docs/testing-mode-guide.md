# Admin Override & General Questions Guide

## Overview

The system supports **Admin Override** functionality and **General Questions** with reduced validation requirements. This provides flexibility for development, testing, and simple Q&A scenarios while maintaining security.

## Admin Override

### For Admin Users
Admin users (configured in `ADMIN_USERS` environment variable) can:
- Process tasks that fail validation (they see warnings but aren't blocked)
- Use any task type with bypass capability
- Perfect for development, testing, and edge cases

**Current admin users**: Check your `.env` file for `ADMIN_USERS` configuration

### Example Admin Usage
```markdown
### Task Type
Code Analysis

### Detailed Prompt
Incomplete task with low validation score - admin can process anyway

What does the login function do?
```

*Admin will see validation warnings but task will process successfully*

## General Questions

### For All Users
Use **"General Question"** task type for:
- Programming concept questions
- Best practice advice
- Architecture guidance
- Quick explanations

**Benefits:**
- **Lower validation threshold** (30/100 instead of 50/100)
- **Simplified processing** (no git worktree needed)
- **Faster responses** (text-only, optimized workflow)
- **"General response"** output format available

### ✅ **Perfect for:**
- **Programming questions** without file analysis
- **Concept explanations** and best practices
- **Architecture advice** and patterns
- **Quick clarifications** on development topics

### ❌ **Not suitable for:**
- **Code analysis** requiring file examination
- **Bug fixes** needing repository context
- **Feature implementation** with code changes

## Example Usage

### Regular Code Task (Requires Score 50+)
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

### General Question (Requires Score 30+)
```markdown
### Task Type
General Question

### Detailed Prompt
How does JWT authentication work in web applications?

### Preferred Output Format
General response

💡 Score: 35/100 → ✅ Processes with simplified workflow
```

### Admin Override Example
```markdown
### Task Type
Code Analysis

### Detailed Prompt
Quick check

🔑 Score: 15/100 → ⚠️ Admin override allows processing
```

## GitHub Feedback Examples

### General Question Mode:
```markdown
💡 **General Question Mode** - Lower validation threshold applied
✅ **Task Validation Successful**
Your task has been validated with a completeness score of 35/100.

⚠️ **Warnings:**
- 💡 General question mode - lower validation threshold applied
```

### Admin Override:
```markdown
🔑 **Admin Override Active**
⚠️ **Validation Override**
Your task scored 15/100 but admin privileges allow processing.

⚠️ **Warnings:**
- 🔑 Admin user detected - validation requirements can be overridden
- ⚠️ Score below threshold (15/100 < 50) but admin override allows processing
```

## Configuration

### Setting Up Admin Users
```bash
# In your .env file
ADMIN_USERS=admin-username,another-admin,dev-lead

# Validation thresholds  
GENERAL_QUESTION_MIN_SCORE=30
STANDARD_MIN_SCORE=50
```

### Admin User Benefits
- **See validation details** but aren't blocked by failures
- **Process any task type** regardless of score
- **Useful for development** and edge case testing
- **Full transparency** with clear override indicators

## Best Practices

### ✅ **Use General Questions For:**
```markdown
How does JWT authentication work?
What's the difference between OAuth and SAML?  
Explain React hooks best practices
What are SOLID principles?
```

### ✅ **Admin Override For:**
- Development and testing scenarios
- Edge cases and quick fixes
- Bypassing validation for urgent tasks
- Experimenting with incomplete requests

### ❌ **Use Full Validation For:**
- Production code analysis
- Complex feature implementations  
- Security-sensitive tasks
- Detailed refactoring requests

## API Integration

For programmatic access:

```python
# Parse issue with author info
parsed_task = issue_parser.parse_issue(issue_body, issue_title, issue_author)

# Check admin status
is_admin = settings.is_admin_user(parsed_task.issue_author)

# Validate with new logic
validation_result = task_validator.validate_task_completeness(parsed_task)
ready = task_validator.is_ready_for_processing(parsed_task)
```

This provides flexible access levels while maintaining security! 🔑💡✅