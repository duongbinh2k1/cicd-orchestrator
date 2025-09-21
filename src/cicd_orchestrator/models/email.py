"""Email processing models."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class ProcessedEmail(Base):
    """Model to track processed GitLab pipeline notification emails."""
    
    @staticmethod
    def _utcnow():
        """Return current UTC datetime without timezone info."""
        return datetime.now(timezone.utc).replace(tzinfo=None)
    
    __tablename__ = "processed_emails"
    
    id = Column(Integer, primary_key=True)
    message_uid = Column(String, unique=True, nullable=False)
    message_id = Column(String, unique=True, nullable=True)  # Email Message-ID header
    received_at = Column(DateTime, nullable=False)  # Email received timestamp without timezone
    from_email = Column(String, nullable=False)
    subject = Column(String)
    
    # GitLab project information
    project_id = Column(String)  # Keep as String for flexibility
    project_name = Column(String)  # X-GitLab-Project
    project_path = Column(String)  # X-GitLab-Project-Path
    
    # GitLab pipeline information
    pipeline_id = Column(String)  # Keep as String for flexibility
    pipeline_ref = Column(String)  # X-GitLab-Pipeline-Ref (branch/tag)
    pipeline_status = Column(String)
    
    # Processing status and metadata
    status = Column(String)  # pending, fetched, fetching_gitlab_data, processing_pipeline, completed, no_gitlab_headers, error
    error_message = Column(Text, nullable=True)  # Có thể chứa HTML content lớn
    gitlab_error_log = Column(Text, nullable=True)  # GitLab job logs for failed pipelines
    
    # Timestamps (to match Oracle table)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    
    def __repr__(self):
        return f"<ProcessedEmail(uid={self.message_uid}, pipeline={self.pipeline_id})>"