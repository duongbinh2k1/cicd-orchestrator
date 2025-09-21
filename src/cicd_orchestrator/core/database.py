"""Database configuration and connection management."""

import asyncio
from typing import Optional
from contextlib import asynccontextmanager

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from .config import settings

logger = structlog.get_logger(__name__)


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


class DatabaseManager:
    """Database connection manager."""
    
    def __init__(self):
        self.engine: Optional[object] = None
        self.session_maker: Optional[async_sessionmaker] = None
        self._is_connected = False
    
    async def initialize(self) -> bool:
        """Initialize database connection."""
        try:
            # Create async engine
            self.engine = create_async_engine(
                settings.database_url,
                echo=settings.database_echo,
                pool_pre_ping=True,
                pool_recycle=3600,
            )
            
            # Create session maker
            self.session_maker = async_sessionmaker(
                bind=self.engine,
                class_=AsyncSession,
                expire_on_commit=False
            )
            
            # Test connection
            await self._test_connection()
            
            logger.info(
                "✅ Database initialized successfully", 
                database_type=self._get_db_type(),
                echo_enabled=settings.database_echo
            )
            
            self._is_connected = True
            return True
            
        except Exception as e:
            logger.error(
                "❌ Database initialization failed", 
                error=str(e),
                database_url=self._mask_db_url()
            )
            self._is_connected = False
            return False
    
    async def _test_connection(self):
        """Test database connection."""
        if not self.engine:
            raise RuntimeError("Database engine not initialized")
            
        async with self.engine.begin() as conn:
            # Test query - Oracle specific
            if "oracle" in settings.database_url.lower():
                result = await conn.execute(text("SELECT 1 FROM DUAL"))
            else:
                # PostgreSQL/SQLite fallback
                result = await conn.execute(text("SELECT 1"))
            # fetchone() is not awaitable in SQLAlchemy 2.0
            row = result.fetchone()
            
        logger.debug("Database connection test successful")
    
    def _get_db_type(self) -> str:
        """Get database type from URL."""
        if "postgresql" in settings.database_url:
            return "postgresql"
        elif "oracle" in settings.database_url:
            return "oracle"
        elif "sqlite" in settings.database_url:
            return "sqlite"
        else:
            return "unknown"
    
    def _mask_db_url(self) -> str:
        """Mask sensitive info in database URL."""
        if '@' in settings.database_url:
            return settings.database_url.split('@')[0] + '@***'
        return settings.database_url
    
    @asynccontextmanager
    async def get_session(self):
        """Get database session context manager."""
        if not self.session_maker:
            raise RuntimeError("Database not initialized")
            
        async with self.session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
    
    async def close(self):
        """Close database connections."""
        if self.engine:
            await self.engine.dispose()
            logger.info("Database connections closed")
            self._is_connected = False
    
    @property
    def is_connected(self) -> bool:
        """Check if database is connected."""
        return self._is_connected
    
    async def create_tables(self):
        """Create all tables."""
        if not self.engine:
            raise RuntimeError("Database engine not initialized")
            
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            
        logger.info("Database tables created/updated")


# Global database manager instance
db_manager = DatabaseManager()


async def get_database_session():
    """Dependency to get database session."""
    if not db_manager.is_connected:
        raise RuntimeError("Database not connected")
        
    async with db_manager.get_session() as session:
        yield session


async def init_database():
    """Initialize database connection and create tables."""
    from .database_setup import create_all_tables
    
    success = await db_manager.initialize()
    if success:
        try:
            # Use the new database setup module
            await create_all_tables(db_manager.engine)
            logger.info("Database setup completed successfully")
        except Exception as e:
            logger.error(
                "Table creation failed",
                error=str(e)
            )
    return success


async def close_database():
    """Close database connections."""
    await db_manager.close()


# Health check functions
async def check_database_health() -> dict:
    """Check database health status."""
    if not db_manager.is_connected:
        return {
            "status": "disconnected",
            "database_type": db_manager._get_db_type(),
            "error": "Database not connected"
        }
    
    try:
        async with db_manager.get_session() as session:
            # Oracle specific health check query
            if "oracle" in settings.database_url.lower():
                await session.execute(text("SELECT 1 FROM DUAL"))
            else:
                # PostgreSQL/SQLite fallback
                await session.execute(text("SELECT 1"))
            
        return {
            "status": "healthy",
            "database_type": db_manager._get_db_type(),
            "echo_enabled": settings.database_echo
        }
        
    except Exception as e:
        return {
            "status": "error", 
            "database_type": db_manager._get_db_type(),
            "error": str(e)
        }
