"""CLI commands for CI/CD Orchestrator."""

import asyncio
import sys
from typing import Optional

import structlog
import typer
from rich.console import Console
from rich.table import Table

from .core.config import settings
from .core.database import init_database, close_database, db_manager
from .core.database_setup import create_all_tables, drop_all_tables, recreate_all_tables

app = typer.Typer(
    name="cicd-orchestrator",
    help="CI/CD Error Analysis Orchestrator CLI",
    add_completion=False,
)

console = Console()
logger = structlog.get_logger(__name__)


@app.command()
def version():
    """Show application version."""
    console.print(f"CI/CD Orchestrator v{settings.app_version}")


@app.command()
def serve(
    host: str = typer.Option(settings.host, "--host", "-h", help="Host to bind"),
    port: int = typer.Option(settings.port, "--port", "-p", help="Port to bind"),
    reload: bool = typer.Option(settings.reload, "--reload", "-r", help="Enable auto-reload"),
):
    """Start the web server."""
    import uvicorn
    
    console.print(f"🚀 Starting CI/CD Orchestrator on {host}:{port}")
    
    uvicorn.run(
        "cicd_orchestrator.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level=settings.log_level.lower(),
    )


@app.command()
def config():
    """Show current configuration."""
    table = Table(title="CI/CD Orchestrator Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")
    
    # Core settings
    table.add_row("Environment", settings.environment)
    table.add_row("Debug", str(settings.debug))
    table.add_row("Host", settings.host)
    table.add_row("Port", str(settings.port))
    table.add_row("Trigger Mode", settings.trigger_mode)
    
    # Database
    table.add_row("Database URL", settings.database_url.split('@')[0] + '@***' if '@' in settings.database_url else settings.database_url)
    
    # AI Provider
    table.add_row("AI Provider", settings.default_ai_provider)
    table.add_row("OpenAI Model", settings.openai_model)
    
    # Email (if enabled)
    if settings.imap_enabled:
        table.add_row("IMAP Enabled", str(settings.imap_enabled))
        table.add_row("IMAP Server", settings.imap_server)
        table.add_row("IMAP User", settings.imap_user)
    
    console.print(table)


@app.command()
def health():
    """Check service health."""
    async def check_health():
        from .core.database import get_database_session
        from .services.orchestration_service import OrchestrationService
        
        try:
            async with get_database_session() as db:
                orchestration_service = OrchestrationService(db)
                health_status = await orchestration_service.health_check()
                
                table = Table(title="Health Check")
                table.add_column("Component", style="cyan")
                table.add_column("Status", style="green")
                
                for component, is_healthy in health_status.items():
                    status_text = "✅ Healthy" if is_healthy else "❌ Unhealthy"
                    table.add_row(component, status_text)
                
                console.print(table)
        except Exception as e:
            console.print(f"❌ Health check failed: {e}")
            sys.exit(1)
    
    asyncio.run(check_health())


@app.command()
def db_create():
    """Create all database tables."""
    async def _create():
        try:
            await init_database()
            console.print("✅ Database tables created successfully")
        except Exception as e:
            console.print(f"❌ Failed to create tables: {e}")
            sys.exit(1)
        finally:
            await close_database()
    
    asyncio.run(_create())


@app.command()
def db_drop():
    """Drop all database tables (WARNING: This will delete all data!)."""
    if not typer.confirm("⚠️  This will delete ALL data. Are you sure?"):
        console.print("Operation cancelled")
        return
    
    async def _drop():
        try:
            success = await db_manager.initialize()
            if success:
                await drop_all_tables(db_manager.engine)
                console.print("✅ Database tables dropped successfully")
            else:
                console.print("❌ Failed to connect to database")
                sys.exit(1)
        except Exception as e:
            console.print(f"❌ Failed to drop tables: {e}")
            sys.exit(1)
        finally:
            await close_database()
    
    asyncio.run(_drop())


@app.command()
def db_recreate():
    """Drop and recreate all database tables (WARNING: This will delete all data!)."""
    if not typer.confirm("⚠️  This will delete ALL data and recreate tables. Are you sure?"):
        console.print("Operation cancelled")
        return
    
    async def _recreate():
        try:
            success = await db_manager.initialize()
            if success:
                await recreate_all_tables(db_manager.engine)
                console.print("✅ Database tables recreated successfully")
            else:
                console.print("❌ Failed to connect to database")
                sys.exit(1)
        except Exception as e:
            console.print(f"❌ Failed to recreate tables: {e}")
            sys.exit(1)
        finally:
            await close_database()
    
    asyncio.run(_recreate())


@app.command()
def db_status():
    """Check database connection and table status."""
    async def _status():
        try:
            success = await db_manager.initialize()
            if success:
                from sqlalchemy import text
                
                async with db_manager.engine.begin() as conn:
                    # Check which tables exist - Oracle version
                    if "oracle" in db_manager._get_db_type():
                        result = await conn.execute(text("""
                            SELECT table_name 
                            FROM user_tables 
                            ORDER BY table_name
                        """))
                    else:
                        # PostgreSQL/SQLite fallback
                        result = await conn.execute(text("""
                            SELECT table_name 
                            FROM information_schema.tables 
                            WHERE table_schema = 'public'
                            ORDER BY table_name
                        """))
                    tables = [row[0] for row in result.fetchall()]
                
                table = Table(title="Database Status")
                table.add_column("Property", style="cyan")
                table.add_column("Value", style="green")
                
                table.add_row("Connection", "✅ Connected")
                table.add_row("Tables Found", str(len(tables)))
                
                if tables:
                    table.add_row("Table Names", ", ".join(tables))
                else:
                    table.add_row("Table Names", "No tables found")
                
                console.print(table)
            else:
                console.print("❌ Failed to connect to database")
                sys.exit(1)
        except Exception as e:
            console.print(f"❌ Database status check failed: {e}")
            sys.exit(1)
        finally:
            await close_database()
    
    asyncio.run(_status())


@app.command()
def test_email():
    """Test email connection and fetch sample emails."""
    async def _test():
        try:
            from .services.email_service import EmailUtils
            
            console.print("🔍 Testing email connection...")
            
            with EmailUtils.get_imap_connection() as mailbox:
                console.print("✅ IMAP connection successful")
                
                # Get some basic stats
                folder_status = mailbox.folder.status()
                console.print(f"📧 Mailbox: {settings.imap_folder}")
                console.print(f"📊 Total messages: {folder_status.get('MESSAGES', 0)}")
                
                # Try to fetch a few recent emails
                recent_emails = list(mailbox.fetch(limit=5, reverse=True))
                console.print(f"📨 Recent emails: {len(recent_emails)}")
                
                for i, msg in enumerate(recent_emails, 1):
                    console.print(f"  {i}. From: {msg.from_} | Subject: {msg.subject[:50]}...")
                
        except Exception as e:
            console.print(f"❌ Email test failed: {e}")
            sys.exit(1)
    
    asyncio.run(_test())


def main():
    """Main CLI entry point."""
    app()


if __name__ == "__main__":
    main()
