"""
Error analysis prompt templates for different types of CI/CD failures.
Version: 1.0
"""

BUILD_FAILURE_TEMPLATE = """
CONTEXT: Build Stage Failure
FOCUS AREAS:
- Compilation errors
- Dependency resolution issues
- Build tool configuration
- Environment setup problems
- Resource constraints

ADDITIONAL CONTEXT:
{additional_context}

ERROR ANALYSIS:
Job: {job_name}
Stage: {stage}
Exit Code: {exit_code}
Duration: {duration}

BUILD LOG:
{log_content}

PROJECT CONTEXT:
{project_context}

CI CONFIGURATION:
{ci_config}
"""

TEST_FAILURE_TEMPLATE = """
CONTEXT: Test Stage Failure
FOCUS AREAS:
- Unit test failures
- Integration test issues
- Test environment problems
- Test data issues
- Coverage requirements

ADDITIONAL CONTEXT:
{additional_context}

ERROR ANALYSIS:
Job: {job_name}
Stage: {stage}
Exit Code: {exit_code}
Test Results: {test_results}

TEST LOG:
{log_content}

PROJECT CONTEXT:
{project_context}

CI CONFIGURATION:
{ci_config}
"""

DEPLOYMENT_FAILURE_TEMPLATE = """
CONTEXT: Deployment Stage Failure
FOCUS AREAS:
- Infrastructure issues
- Configuration problems
- Permission/access issues
- Service dependencies
- Resource availability

ADDITIONAL CONTEXT:
{additional_context}

ERROR ANALYSIS:
Job: {job_name}
Stage: {stage}
Exit Code: {exit_code}
Environment: {environment}

DEPLOYMENT LOG:
{log_content}

PROJECT CONTEXT:
{project_context}

CI CONFIGURATION:
{ci_config}

INFRASTRUCTURE INFO:
{infrastructure_info}
"""

GENERIC_FAILURE_TEMPLATE = """
CONTEXT: General CI/CD Pipeline Failure
FOCUS AREAS:
- Pipeline configuration
- Job dependencies
- Environment issues
- Resource problems

ADDITIONAL CONTEXT:
{additional_context}

ERROR ANALYSIS:
Job: {job_name}
Stage: {stage}
Exit Code: {exit_code}
Status: {status}

ERROR LOG:
{log_content}

PROJECT CONTEXT:
{project_context}

CI CONFIGURATION:
{ci_config}

ADDITIONAL FILES:
{repository_files}
"""

SECURITY_SCAN_FAILURE_TEMPLATE = """
CONTEXT: Security Scan Failure
FOCUS AREAS:
- Known vulnerabilities (CVEs)
- Code security issues (SAST)
- Dependency vulnerabilities
- Security compliance violations
- License compliance issues
- Container security
- Secret detection

ADDITIONAL CONTEXT:
{additional_context}

ERROR ANALYSIS:
Job: {job_name}
Stage: {stage}
Exit Code: {exit_code}
Severity: {severity}
Scan Type: {scan_type}

SCAN RESULTS:
{log_content}

PROJECT CONTEXT:
{project_context}

SECURITY CONFIGURATION:
{security_config}

DEPENDENCY INFO:
{dependency_info}

COMPLIANCE REQUIREMENTS:
{compliance_info}
"""

PERFORMANCE_TEST_FAILURE_TEMPLATE = """
CONTEXT: Performance Test Failure
FOCUS AREAS:
- Response time thresholds
- Resource utilization
- Throughput limits
- Concurrency issues
- Memory leaks
- Database performance
- API performance

ADDITIONAL CONTEXT:
{additional_context}

ERROR ANALYSIS:
Job: {job_name}
Stage: {stage}
Exit Code: {exit_code}
Duration: {duration}

TEST CONFIGURATION:
- Virtual Users: {vusers}
- Test Duration: {duration}
- Target URLs: {target_urls}

PERFORMANCE METRICS:
{metrics}

ERROR LOG:
{log_content}

SYSTEM RESOURCES:
{resource_usage}

BASELINE COMPARISON:
{baseline_comparison}
"""

# Dictionary of all error templates
ERROR_TEMPLATES = {
    'build': BUILD_FAILURE_TEMPLATE,
    'test': TEST_FAILURE_TEMPLATE,
    'deploy': DEPLOYMENT_FAILURE_TEMPLATE,
    'security': SECURITY_SCAN_FAILURE_TEMPLATE,
    'performance': PERFORMANCE_TEST_FAILURE_TEMPLATE,
    'generic': GENERIC_FAILURE_TEMPLATE
}
