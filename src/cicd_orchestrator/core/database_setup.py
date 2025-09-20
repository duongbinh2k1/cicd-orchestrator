"""Database table creation and management."""

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ..models.email import ProcessedEmail

logger = structlog.get_logger(__name__)


async def create_all_tables(engine: AsyncEngine) -> None:
    """Create all application tables.
    
    This function creates all necessary database tables for the application.
    Add new table creation logic here when adding new models.
    
    Args:
        engine: AsyncEngine instance for database operations
    """
    async with engine.begin() as conn:
        try:
            # Create processed_emails table
            await create_processed_emails_table(conn)
            
            logger.info("All database tables created successfully")
            
        except Exception as e:
            logger.error("Failed to create database tables", error=str(e))
            raise


async def create_processed_emails_table(conn) -> None:
    """Create the processed_emails table."""
    
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS processed_emails (
        id SERIAL PRIMARY KEY,
        message_uid VARCHAR(255) NOT NULL,
        message_id VARCHAR(500),
        received_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
        from_email VARCHAR(255) NOT NULL,
        subject TEXT NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'pending',
        
        -- GitLab specific fields
        project_id INTEGER,
        project_name VARCHAR(255),
        project_path VARCHAR(500),
        pipeline_id INTEGER,
        pipeline_ref VARCHAR(255),
        pipeline_status VARCHAR(50),
        
        -- Error and analysis data
        error_message TEXT,
        gitlab_error_log TEXT,
        
        -- Timestamps
        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        
        -- Indexes for performance
        UNIQUE(message_uid),
        UNIQUE(message_id)
    );
    """
    
    # Create indexes
    create_indexes_sql = [
        "CREATE INDEX IF NOT EXISTS idx_processed_emails_status ON processed_emails(status);",
        "CREATE INDEX IF NOT EXISTS idx_processed_emails_project_id ON processed_emails(project_id);",
        "CREATE INDEX IF NOT EXISTS idx_processed_emails_pipeline_id ON processed_emails(pipeline_id);",
        "CREATE INDEX IF NOT EXISTS idx_processed_emails_received_at ON processed_emails(received_at);",
        "CREATE INDEX IF NOT EXISTS idx_processed_emails_from_email ON processed_emails(from_email);"
    ]
    
    try:
        # Create table
        await conn.execute(text(create_table_sql))
        logger.info("Created processed_emails table")
        
        # Create indexes
        for index_sql in create_indexes_sql:
            await conn.execute(text(index_sql))
        logger.info("Created indexes for processed_emails table")
        
    except Exception as e:
        logger.error("Failed to create processed_emails table", error=str(e))
        raise


async def drop_all_tables(engine: AsyncEngine) -> None:
    """Drop all application tables.
    
    WARNING: This will delete all data!
    Use only for development/testing.
    
    Args:
        engine: AsyncEngine instance for database operations
    """
    async with engine.begin() as conn:
        try:
            # Drop tables in reverse dependency order
            await conn.execute(text("DROP TABLE IF EXISTS processed_emails CASCADE;"))
            
            logger.warning("All database tables dropped")
            
        except Exception as e:
            logger.error("Failed to drop database tables", error=str(e))
            raise


async def recreate_all_tables(engine: AsyncEngine) -> None:
    """Drop and recreate all tables.
    
    WARNING: This will delete all data!
    Use only for development/testing.
    
    Args:
        engine: AsyncEngine instance for database operations
    """
    logger.warning("Recreating all database tables - ALL DATA WILL BE LOST!")
    
    await drop_all_tables(engine)
    await create_all_tables(engine)
    
    logger.info("Database tables recreated successfully")


# Example function for adding new tables
async def create_example_new_table(conn) -> None:
    """Example of how to add a new table.
    
    When you need to add a new table:
    1. Create a function like this
    2. Add the call to create_all_tables()
    3. Add drop statement to drop_all_tables()
    """
    
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS example_table (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    """
    
    try:
        await conn.execute(text(create_table_sql))
        logger.info("Created example_table")
        
    except Exception as e:
        logger.error("Failed to create example_table", error=str(e))
        raise