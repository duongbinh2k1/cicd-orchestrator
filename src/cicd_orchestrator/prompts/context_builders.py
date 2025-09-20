"""
Context builders for enriching prompts with additional information.
Version: 1.0
"""

def build_project_context(project_info):
    """Build project context string from GitLab project info."""
    if not project_info:
        return "No project context available"
    
    # Handle both object and dict formats
    if hasattr(project_info, 'project'):
        project = project_info.project
    elif isinstance(project_info, dict) and 'project' in project_info:
        project = project_info['project']
    else:
        project = project_info
    
    # Handle both object and dict formats for project data
    def get_value(obj, key, default='Unknown'):
        if hasattr(obj, key):
            return getattr(obj, key) or default
        elif isinstance(obj, dict):
            return obj.get(key, default)
        return default
    
    context_parts = [
        f"Project: {get_value(project, 'name')}",
        f"Namespace: {get_value(project, 'namespace')}",
        f"Description: {get_value(project, 'description', 'No description')}",
        f"Default Branch: {get_value(project, 'default_branch')}",
        f"Language: {get_value(project, 'programming_language', 'Unknown')}",
    ]
    
    # Handle topics
    topics = get_value(project, 'topics', None)
    if topics:
        context_parts.append(f"Topics: {', '.join(topics)}")
    
    # Handle recent commits
    if hasattr(project_info, 'recent_commits') and project_info.recent_commits:
        context_parts.append("Recent Commits:")
        for commit in project_info.recent_commits[:3]:
            context_parts.append(f"  - {commit.get('title', 'No title')} ({commit.get('author_name', 'Unknown')})")
    elif isinstance(project_info, dict) and 'recent_commits' in project_info:
        context_parts.append("Recent Commits:")
        for commit in project_info['recent_commits'][:3]:
            context_parts.append(f"  - {commit.get('title', 'No title')} ({commit.get('author_name', 'Unknown')})")
    
    return "\n".join(context_parts)


def build_ci_config_context(ci_config):
    """Build CI configuration context string."""
    if not ci_config:
        return "No CI configuration available"
    
    context_parts = ["CI/CD Configuration:"]
    
    # Extract key sections
    if 'stages' in ci_config:
        context_parts.append(f"Stages: {', '.join(ci_config['stages'])}")
    
    if 'variables' in ci_config:
        context_parts.append("Variables:")
        for key, value in ci_config['variables'].items():
            # Hide sensitive values
            if any(sensitive in key.lower() for sensitive in ['password', 'token', 'key', 'secret']):
                value = "[HIDDEN]"
            context_parts.append(f"  {key}: {value}")
    
    if 'before_script' in ci_config:
        context_parts.append("Before Script:")
        for script in ci_config['before_script']:
            context_parts.append(f"  - {script}")
    
    # Extract job definitions (first few)
    jobs = {k: v for k, v in ci_config.items() 
            if isinstance(v, dict) and k not in ['stages', 'variables', 'before_script', 'after_script']}
    
    if jobs:
        context_parts.append("Job Definitions:")
        for job_name, job_config in list(jobs.items())[:5]:  # Limit to first 5 jobs
            context_parts.append(f"  {job_name}:")
            if 'stage' in job_config:
                context_parts.append(f"    stage: {job_config['stage']}")
            if 'script' in job_config:
                scripts = job_config['script'][:3]  # First 3 commands
                for script in scripts:
                    context_parts.append(f"    - {script}")
                if len(job_config['script']) > 3:
                    context_parts.append(f"    ... and {len(job_config['script']) - 3} more commands")
    
    return "\n".join(context_parts)


def build_environment_context(stage, job_name):
    """Build environment-specific context based on stage and job name."""
    context_parts = []
    
    # Stage-specific context
    stage_contexts = {
        'build': [
            "Common build issues: dependency conflicts, compilation errors, missing tools",
            "Check: package.json/requirements.txt, Dockerfile, build scripts"
        ],
        'test': [
            "Common test issues: environment setup, test data, database connections",
            "Check: test configuration, test environment variables, test databases"
        ],
        'deploy': [
            "Common deploy issues: credentials, network access, resource limits",
            "Check: deployment credentials, target environment, resource quotas"
        ]
    }
    
    if stage.lower() in stage_contexts:
        context_parts.extend(stage_contexts[stage.lower()])
    
    # Job name patterns
    if 'docker' in job_name.lower():
        context_parts.append("Docker-related: Check Dockerfile, image layers, registry access")
    elif 'npm' in job_name.lower() or 'node' in job_name.lower():
        context_parts.append("Node.js-related: Check package.json, node_modules, npm registry")
    elif 'maven' in job_name.lower() or 'gradle' in job_name.lower():
        context_parts.append("Java-related: Check pom.xml/build.gradle, dependencies, JVM settings")
    elif 'pip' in job_name.lower() or 'python' in job_name.lower():
        context_parts.append("Python-related: Check requirements.txt, virtual env, Python version")
    
    return "\n".join(context_parts) if context_parts else "No specific environment context"


def build_error_context(log_content, max_lines=100):
    """Extract and format error context from log content."""
    if not log_content:
        return "No log content available"
    
    lines = log_content.split('\n')
    
    # If log is short, return as-is
    if len(lines) <= max_lines:
        return log_content
    
    # Find error indicators
    error_patterns = [
        'error:', 'Error:', 'ERROR:', 'FAILED:', 'failed:',
        'exception:', 'Exception:', 'EXCEPTION:',
        'fatal:', 'Fatal:', 'FATAL:',
        'build failed', 'test failed', 'compilation failed'
    ]
    
    error_lines = []
    for i, line in enumerate(lines):
        if any(pattern in line for pattern in error_patterns):
            # Include context around error
            start = max(0, i - 5)
            end = min(len(lines), i + 10)
            error_lines.extend(range(start, end))
    
    if error_lines:
        # Remove duplicates and sort
        error_lines = sorted(set(error_lines))
        context_lines = []
        
        prev_line = -1
        for line_num in error_lines:
            if line_num > prev_line + 1:
                context_lines.append("... [context gap] ...")
            context_lines.append(f"{line_num + 1:4d}: {lines[line_num]}")
            prev_line = line_num
        
        return "\n".join(context_lines)
    else:
        # No specific errors found, return last portion
        return "\n".join(lines[-max_lines:])


def build_repository_files_context(repository_files):
    """Build context from repository file list."""
    if not repository_files:
        return "No repository files information available"
    
    context_parts = ["Repository Files:"]
    
    # Group files by type
    config_files = []
    source_files = []
    doc_files = []
    
    for file_info in repository_files:
        name = file_info.get('name', '').lower()
        if any(config in name for config in ['.yml', '.yaml', '.json', '.toml', '.ini', 'dockerfile', 'makefile']):
            config_files.append(file_info['name'])
        elif any(ext in name for ext in ['.py', '.js', '.ts', '.java', '.go', '.rs', '.cpp', '.c']):
            source_files.append(file_info['name'])
        elif any(ext in name for ext in ['.md', '.txt', '.rst', '.pdf']):
            doc_files.append(file_info['name'])
    
    if config_files:
        context_parts.append("Configuration Files:")
        for file_name in config_files[:10]:  # Limit to 10
            context_parts.append(f"  - {file_name}")
    
    if source_files:
        context_parts.append("Source Files:")
        for file_name in source_files[:5]:  # Limit to 5
            context_parts.append(f"  - {file_name}")
    
    return "\n".join(context_parts)
