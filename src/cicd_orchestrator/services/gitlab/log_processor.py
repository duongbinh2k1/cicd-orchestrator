"""Log processing utilities for GitLab job logs."""

from typing import Optional


class LogProcessor:
    """Utilities for processing and filtering GitLab job logs."""

    @staticmethod
    def process_log_content(
        log_content: str, 
        max_size_mb: Optional[int] = None,
        context_lines: Optional[int] = None,
        job_status: str = "failed"
    ) -> str:
        """Process log content based on size and context constraints.
        
        Args:
            log_content: Raw log content
            max_size_mb: Maximum log size in MB (None for no limit)
            context_lines: Number of context lines around errors (None for full log)
            job_status: Job status to determine processing strategy
            
        Returns:
            Processed log content
        """
        
        # Apply size limit first
        if max_size_mb:
            max_bytes = max_size_mb * 1024 * 1024
            if len(log_content.encode('utf-8')) > max_bytes:
                # Take the last portion of the log (where errors usually are)
                log_content = log_content[-max_bytes//2:]  # Take last half
                log_content = "... [LOG TRUNCATED DUE TO SIZE] ...\n" + log_content
        
        # Apply context filtering for failed jobs
        if context_lines and job_status in ["failed", "canceled"] and log_content:
            log_content = LogProcessor.extract_error_context(log_content, context_lines)
        
        return log_content
    
    @staticmethod
    def extract_error_context(log_content: str, context_lines: int) -> str:
        """Extract relevant error context from log content.
        
        Args:
            log_content: Full log content
            context_lines: Number of lines to include around errors
            
        Returns:
            Filtered log content with error context
        """
        lines = log_content.split('\n')
        
        # Common error indicators
        error_patterns = [
            'error:', 'Error:', 'ERROR:', 'FAILED:', 'failed:',
            'exception:', 'Exception:', 'EXCEPTION:',
            'fatal:', 'Fatal:', 'FATAL:',
            'build failed', 'Build failed', 'BUILD FAILED',
            'test failed', 'Test failed', 'TEST FAILED',
            'compilation failed', 'Compilation failed',
            'exit code', 'Exit code', 'exit status'
        ]
        
        error_line_indices = []
        for i, line in enumerate(lines):
            if any(pattern in line for pattern in error_patterns):
                error_line_indices.append(i)
        
        if not error_line_indices:
            # If no specific errors found, return the last portion
            return '\n'.join(lines[-context_lines*2:])
        
        # Extract context around error lines
        context_lines_set = set()
        for error_idx in error_line_indices:
            start = max(0, error_idx - context_lines)
            end = min(len(lines), error_idx + context_lines + 1)
            context_lines_set.update(range(start, end))
        
        # Sort and extract context
        sorted_indices = sorted(context_lines_set)
        context_content = []
        
        prev_idx = -1
        for idx in sorted_indices:
            if idx > prev_idx + 1:
                context_content.append("... [CONTEXT GAP] ...")
            context_content.append(f"{idx+1:4d}: {lines[idx]}")
            prev_idx = idx
        
        return '\n'.join(context_content)