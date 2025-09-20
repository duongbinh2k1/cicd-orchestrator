"""CLI commands for CI/CD Orchestrator."""

import asyncio
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .core.config import settings
from .services.orchestration_service import OrchestrationService

app = typer.Typer()
console = Console()


@app.command()
def version():
    """Show application version."""
    console.print(f"CI/CD Orchestrator v{settings.app_version}")


@app.command()
def config():
    """Show current configuration."""
    table = Table(title="Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Environment", settings.environment)
    table.add_row("Host", settings.host)
    table.add_row("Port", str(settings.port))
    table.add_row("Debug", str(settings.debug))
    table.add_row("GitLab URL", settings.gitlab_base_url)
    table.add_row("Default AI Provider", settings.default_ai_provider)
    table.add_row("Log Level", settings.log_level)
    
    console.print(table)


@app.command()
def health():
    """Check service health."""
    async def check_health():
        orchestration_service = OrchestrationService()
        health_status = await orchestration_service.health_check()
        
        table = Table(title="Health Check")
        table.add_column("Component", style="cyan")
        table.add_column("Status", style="green")
        
        for component, is_healthy in health_status.items():
            status_text = "✅ Healthy" if is_healthy else "❌ Unhealthy"
            table.add_row(component, status_text)
        
        console.print(table)
    
    asyncio.run(check_health())


@app.command()
def serve(
    host: str = typer.Option(settings.host, help="Host to bind to"),
    port: int = typer.Option(settings.port, help="Port to bind to"),
    reload: bool = typer.Option(settings.reload, help="Enable auto-reload"),
):
    """Start the CI/CD Orchestrator server."""
    import uvicorn
    
    console.print(f"Starting CI/CD Orchestrator on {host}:{port}")
    
    uvicorn.run(
        "cicd_orchestrator.main:app",
        host=host,
        port=port,
        reload=reload,
        log_config=None,
    )


def main():
    """Main CLI entry point."""
    app()


if __name__ == "__main__":
    main()
