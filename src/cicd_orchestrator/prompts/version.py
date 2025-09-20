"""
Prompt template version information.
This file tracks the version of the prompt system for easy management.
"""

PROMPT_SYSTEM_VERSION = "1.0.0"
LAST_UPDATED = "2025-09-19"

# Version history
VERSION_HISTORY = [
    {
        "version": "1.0.0",
        "date": "2025-09-19", 
        "changes": [
            "Initial prompt template system",
            "Base system prompt with structured JSON response",
            "Specialized error templates for build/test/deploy failures",
            "Dynamic context builders for GitLab data",
            "Modular prompt loader with template selection"
        ]
    }
]

# Template compatibility
TEMPLATE_COMPATIBILITY = {
    "base_system": "1.0.0",
    "error_templates": "1.0.0", 
    "context_builders": "1.0.0",
    "prompt_loader": "1.0.0"
}
