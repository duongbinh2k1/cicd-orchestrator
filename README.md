# CI/CD Orchestrator

An AI-powered CI/CD error analysis and remediation orchestrator that automatically analyzes failed pipelines and provides intelligent solutions. Supports both **GitLab webhooks** and **email monitoring** for comprehensive pipeline failure detection.

## Features

- 🔗 **GitLab Integration**: Receives webhooks from GitLab for pipeline and job events
- 📧 **Email Monitoring**: Monitors IMAP inbox for GitLab pipeline failure notifications
- 🤖 **AI-Powered Analysis**: Uses OpenAI, Anthropic, and other AI providers to analyze errors
- 📊 **Comprehensive Reporting**: Provides detailed error analysis with root cause and solutions
- 🚀 **FastAPI Backend**: Modern, async Python web framework
- 🐳 **Docker Support**: Containerized deployment with Docker Compose
- 📈 **Monitoring**: Built-in health checks and logging
- 🔐 **Security**: Webhook signature verification and secure configuration
- 🗄️ **Database Management**: Simple CLI-based database setup and management

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL database
- Docker and Docker Compose (optional)
- GitLab instance with API access (for webhook mode)
- Email account with IMAP access (for email mode)
- OpenAI or Anthropic API key

### Installation

1. **Clone the repository**
```bash
git clone <repository-url>
cd cicd-orchestrator
```

2. **Set up Python environment**
```bash
# Create virtual environment
python -m venv .venv

# Activate environment
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows
```

3. **Install dependencies**
```bash
# Using pip
pip install -e ".[dev]"   # Include development dependencies
pip install -e .          # Production only

# Using uv (recommended for faster installs)
uv pip install -e ".[dev]"
```

4. **Configure environment variables**
```bash
cp .env.example .env
# Edit .env with your configuration
```

5. **Set up database**
```bash
# Create database tables
python -m src.cicd_orchestrator.cli db-create

# Check database status
python -m src.cicd_orchestrator.cli db-status
```

6. **Start the application**
```bash
# Using CLI (recommended)
python -m src.cicd_orchestrator.cli serve

# Or using uvicorn directly
uvicorn src.cicd_orchestrator.main:app --reload --host 0.0.0.0 --port 8000
```

7. **Verify installation**
```bash
# Check health endpoint
curl http://localhost:8000/health

# Test webhook endpoint (if using webhook mode)
curl -X POST http://localhost:8000/test/webhook/custom \
  -H "Content-Type: application/json" \
  -d '{"project_id": 1001, "pipeline_status": "failed"}'

# Test email connection (if using email mode)
python -m src.cicd_orchestrator.cli test-email
```

### Docker Deployment

1. **Build and run with Docker Compose**
```bash
docker-compose up -d
```

2. **Check logs**
```bash
docker-compose logs -f app
```

## Configuration

### Trigger Modes

The orchestrator supports three trigger modes:

```bash
# Webhook mode - receive GitLab webhooks directly
TRIGGER_MODE=webhook

# Email mode - monitor IMAP inbox for failure notifications  
TRIGGER_MODE=email

# Both modes - support both webhook and email triggers
TRIGGER_MODE=both
```

### Core Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `SECRET_KEY` | Application secret key | Yes | - |
| `TRIGGER_MODE` | How to trigger analysis (webhook/email/both) | No | webhook |
| `DATABASE_URL` | PostgreSQL connection URL | Yes | - |
| `OPENAI_API_KEY` | OpenAI API key | Yes | - |
| `OPENAI_BASE_URL` | OpenAI API base URL (for OpenRouter) | No | - |
| `LOG_LEVEL` | Logging level | No | INFO |
| `ENVIRONMENT` | Environment (development/production) | No | development |

### GitLab Configuration (for webhook mode)

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `GITLAB_API_TOKEN` | GitLab API token | Yes | - |
| `GITLAB_BASE_URL` | GitLab instance URL | No | https://gitlab.com |
| `GITLAB_WEBHOOK_SECRET` | Webhook secret for verification | No | - |
| `GITLAB_AUTO_FETCH_LOGS` | Auto-fetch logs from GitLab API | No | true |
| `GITLAB_FETCH_FULL_PIPELINE` | Fetch all jobs for context | No | true |
| `GITLAB_LOG_LINES_LIMIT` | Max log lines to fetch | No | 2000 |

### Email Configuration (for email mode)

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `IMAP_ENABLED` | Enable email monitoring | No | false |
| `IMAP_SERVER` | IMAP server hostname | Yes* | imap.gmail.com |
| `IMAP_PORT` | IMAP server port | No | 993 |
| `IMAP_USE_SSL` | Use SSL for IMAP connection | No | true |
| `IMAP_USER` | IMAP username/email | Yes* | - |
| `IMAP_APP_PASSWORD` | IMAP password/app password | Yes* | - |
| `IMAP_FOLDER` | Email folder to monitor | No | INBOX |
| `IMAP_CHECK_INTERVAL` | Check interval in seconds | No | 60 |
| `IMAP_GITLAB_EMAIL` | Expected GitLab sender email | Yes* | - |

*Required when `TRIGGER_MODE=email` or `TRIGGER_MODE=both`

### Email Setup for GitLab Integration

1. **Configure GitLab to send failure notifications**
   - Go to Project → Settings → Integrations → Emails on push
   - Enable "Send from committer" 
   - Add your monitoring email address
   - Enable for "Failed pipelines" only

2. **Set up email account**
   ```bash
   # Gmail example
   IMAP_SERVER=imap.gmail.com
   IMAP_USER=your-email@gmail.com
   IMAP_APP_PASSWORD=your-app-password  # Not regular password!
   IMAP_GITLAB_EMAIL=noreply@gitlab.com  # Or your GitLab instance email
   ```

3. **Gmail App Password Setup**
   - Enable 2-factor authentication
   - Generate app password for the application
   - Use app password, not regular password

## Database Management

The orchestrator includes a simple CLI-based database management system:

```bash
# Check database status and existing tables
python -m src.cicd_orchestrator.cli db-status

# Create all required tables
python -m src.cicd_orchestrator.cli db-create

# Drop all tables (WARNING: deletes all data!)
python -m src.cicd_orchestrator.cli db-drop

# Recreate all tables (WARNING: deletes all data!)
python -m src.cicd_orchestrator.cli db-recreate

# Show current configuration
python -m src.cicd_orchestrator.cli config

# Test email connection
python -m src.cicd_orchestrator.cli test-email
```

### Adding New Tables

To add new database tables:

1. **Create model** in `src/cicd_orchestrator/models/`
2. **Add table creation function** in `src/cicd_orchestrator/core/database_setup.py`
3. **Update `create_all_tables()`** to include your new table
4. **Update `drop_all_tables()`** to include drop statement
5. **Run** `python -m src.cicd_orchestrator.cli db-recreate`

Example:
```python
# In database_setup.py
async def create_my_new_table(conn) -> None:
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS my_new_table (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    await conn.execute(text(create_table_sql))
    logger.info("Created my_new_table")

# Add to create_all_tables()
await create_my_new_table(conn)
```

### GitLab Data Fetching Strategy

The orchestrator supports multiple strategies for obtaining error logs and context:

1. **Webhook-based** (fastest): Use error data included in GitLab webhooks
2. **API-based** (comprehensive): Fetch complete logs and context via GitLab API
3. **Hybrid** (recommended): Use webhook data when sufficient, fallback to API

Configure with these options:

```bash
# Enable automatic log fetching when webhook data is insufficient
GITLAB_AUTO_FETCH_LOGS=true

# Fetch all pipeline jobs for better context (not just failed ones)
GITLAB_FETCH_FULL_PIPELINE=true

# Download build artifacts for analysis (can be large files)
GITLAB_FETCH_ARTIFACTS=false

# Fetch test reports and coverage data
GITLAB_FETCH_TEST_REPORTS=true

# Limit log file size to prevent memory issues
GITLAB_MAX_LOG_SIZE_MB=10

# Extract context lines around errors (for large logs)
GITLAB_LOG_CONTEXT_LINES=50
```

### GitLab Webhook Setup (for webhook mode)

1. **Go to your GitLab project settings**
   - Project → Settings → Webhooks

2. **Add webhook URL**
   ```
   https://your-domain.com/webhooks/gitlab
   ```

3. **Select events**
   - ✅ Pipeline events
   - ✅ Job events

4. **Configure secret token** (optional but recommended)
   - Set `GITLAB_WEBHOOK_SECRET` environment variable

### Email Monitoring Setup (for email mode)

The email monitoring system processes GitLab pipeline failure notifications sent to an IMAP inbox:

#### How it works:
```
GitLab Pipeline Fails → GitLab sends email → IMAP inbox → Orchestrator monitors → AI Analysis
```

#### Setup process:

1. **Configure GitLab email notifications**
   - Project → Settings → Integrations → Emails on push
   - Add your monitoring email address
   - Configure to send only for failed pipelines

2. **Set up IMAP monitoring**
   ```bash
   IMAP_ENABLED=true
   IMAP_SERVER=imap.gmail.com
   IMAP_USER=monitoring@yourcompany.com
   IMAP_APP_PASSWORD=your-app-password
   IMAP_GITLAB_EMAIL=noreply@gitlab.yourcompany.com
   IMAP_CHECK_INTERVAL=60  # Check every 60 seconds
   ```

3. **Email processing features**
   - ✅ Automatic duplicate detection (avoids reprocessing same failures)
   - ✅ GitLab header extraction (project ID, pipeline ID, etc.)
   - ✅ Failure keyword filtering (only processes actual failures)
   - ✅ Full integration with GitLab API (fetches logs and context)
   - ✅ Database tracking of processed emails

#### Supported email providers:
- **Gmail**: Use app passwords (not regular password)
- **Outlook/Office365**: Use app passwords or OAuth
- **Custom IMAP servers**: Standard IMAP over SSL

## API Documentation

### Endpoints

#### Webhook Endpoints
- `POST /webhooks/gitlab` - Main GitLab webhook handler
- `POST /webhooks/gitlab/test` - Test webhook payload validation
- `GET /webhooks/gitlab/info` - Get webhook configuration info

#### Analysis Endpoints
- `GET /analysis/{request_id}` - Get analysis status and results
- `GET /analysis` - List active analyses
- `GET /analysis/stats/summary` - Get analysis statistics

#### Test Endpoints
- `POST /test/webhook/custom` - Create custom test webhook
- `GET /test/scenarios` - List available test scenarios
- `GET /test/scenarios/{scenario_name}` - Trigger test scenario
- `GET /test/mock/projects` - Get mock project data
- `GET /test/mock/users` - Get mock user data
- `POST /test/mock/reload` - Reload mock data

#### System Endpoints
- `GET /health` - Basic health check
- `GET /health/detailed` - Detailed system status
- `GET /docs` - Interactive API documentation
- `GET /openapi.json` - OpenAPI schema

### Webhook Payload

The application processes GitLab webhooks for:
- Pipeline failures
- Job failures
- Build errors
- Test failures
- Deployment issues

## AI Analysis System

The orchestrator includes a sophisticated AI analysis system with modular prompt management:

### Prompt Template System

```
src/cicd_orchestrator/prompts/
├── __init__.py           # Module exports
├── base_system.py        # Core system prompt for AI analysis
├── error_templates.py    # Specialized templates for different error types
├── context_builders.py   # Functions to build rich context from GitLab data
└── prompt_loader.py      # Dynamic prompt loading and formatting
```

#### Key Features:
- **Modular Templates**: Separate templates for build, test, deployment, and generic failures
- **Dynamic Context**: Enriches prompts with project info, CI config, and error details
- **Version Control**: Easy to update and maintain prompt versions
- **Extensible**: Simple to add new error types or context builders

#### Usage:
```python
from cicd_orchestrator.prompts import prompt_loader

# Build complete analysis prompt with context
prompt = prompt_loader.build_analysis_prompt(
    pipeline_data={'job': {...}, 'pipeline': {...}},
    gitlab_data={'project_info': {...}, 'ci_config': {...}},
    error_context="Error log content..."
)
```

### AI Providers

### OpenAI
```bash
export OPENAI_API_KEY="your-openai-api-key"
export DEFAULT_AI_PROVIDER="openai"
```

### Anthropic
```bash
export ANTHROPIC_API_KEY="your-anthropic-api-key" 
export DEFAULT_AI_PROVIDER="anthropic"
```

### Azure OpenAI
```bash
export AZURE_OPENAI_API_KEY="your-azure-api-key"
export AZURE_OPENAI_ENDPOINT="your-azure-endpoint"
export DEFAULT_AI_PROVIDER="azure_openai"
```

## Architecture

### Flexible Trigger System
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│     GitLab      │───▶│  CI/CD Orchestr │───▶│   AI Provider   │
│   (Webhooks)    │    │      ator       │    │  (OpenAI/etc)   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
        │                        │                        │
┌─────────────────┐              │                        │
│     GitLab      │              ▼                        │
│   (Email        │───▶┌─────────────────┐                │
│   Notifications)│    │    Database     │                │
└─────────────────┘    │   (PostgreSQL)  │                │
                       └─────────────────┘                │
                                 │                        │
                                 ▼                        │
                       ┌─────────────────┐                │
                       │   Results       │◀───────────────┘
                       │   Storage       │
                       └─────────────────┘
```

### Email Processing Flow
```
IMAP Monitor → Email Validation → GitLab Header Extraction → Database Storage → AI Analysis
    (60s)         (failure only)         (project/pipeline)        (dedup)        (same as webhook)
```

### Enhanced Webhook Processing Flow
```
GitLab Webhook → FastAPI Handler → Async Background Task → GitLab Fetch → AI Analysis → Results
     (< 100ms)     (validation)     (non-blocking)       (logs/context)  (smart prompts)
                   (signature)       (error handling)     (test reports)  (solutions)
                   (normalization)   (retry logic)        (artifacts)     (prevention)
```

### Key Benefits:
- **Multiple Trigger Sources**: Support both webhooks and email monitoring
- **Fast Webhook Response**: Returns in < 100ms, preventing GitLab timeouts
- **Robust Email Processing**: Duplicate detection, header parsing, failure filtering
- **Unified Analysis Pipeline**: Both triggers use the same AI analysis workflow
- **Robust Async Processing**: Properly handled async background tasks with error recovery
- **Smart GitLab Integration**: Intelligent fetching strategy for logs and context
- **Enhanced Error Handling**: Comprehensive error catching and logging at all levels
- **Advanced AI Analysis**: Context-aware prompts with multiple AI provider support
- **Database Tracking**: Full audit trail of processed webhooks and emails
```

### Data Fetching Flow

The orchestrator uses an intelligent data fetching strategy:

```
GitLab Webhook Received
         │
         ▼
   Analyze Webhook Data
         │
    ┌────▼────┐
    │Sufficient│ Yes ──▶ Use Webhook Data
    │   Data?  │
    └────┬────┘
         │ No
         ▼
  Fetch from GitLab API
         │
    ┌────▼────┐
    │ Fetch   │
    │ Strategy│
    └────┬────┘
         │
    ┌────▼────┐
    │ Failed  │ ──▶ Get job logs + context
    │ Jobs    │
    │ Only?   │
    └────┬────┘
         │ No (GITLAB_FETCH_FULL_PIPELINE=true)
         ▼
    ┌────────────┐
    │ Full       │ ──▶ Get all jobs for context
    │ Pipeline   │     + test reports
    │ Context    │     + artifacts info
    └────────────┘
         │
         ▼
    AI Analysis with
    Complete Context
```

**Benefits of this approach:**
- **Fast response** when webhook has sufficient data
- **Comprehensive analysis** when API fetch is needed  
- **Context-aware** AI analysis with full pipeline information
- **Size-optimized** log processing to prevent memory issues

## Development

### Setup Development Environment

1. **Install development dependencies**
```bash
pip install -e ".[dev]"
```

2. **Setup pre-commit hooks**
```bash
pre-commit install
```

3. **Run tests**
```bash
pytest
```

4. **Code formatting**
```bash
black .
isort .
```

5. **Type checking**
```bash
mypy .
```

### Project Structure

```
cicd-orchestrator/
├── src/cicd_orchestrator/
│   ├── api/                  # FastAPI routes and dependencies
│   ├── core/                 # Configuration, logging, exceptions, database
│   │   ├── database.py       # Database connection management
│   │   ├── database_setup.py # Table creation and management
│   │   └── config.py         # Settings and environment variables
│   ├── models/               # Pydantic models
│   │   ├── email.py          # Email processing models
│   │   ├── gitlab.py         # GitLab webhook and API models
│   │   └── orchestrator.py   # Orchestration workflow models
│   ├── services/             # Business logic services & external clients
│   │   ├── orchestration_service.py  # Main business logic + email monitoring
│   │   ├── email_service.py          # Email processing utilities
│   │   ├── ai_service.py             # AI providers (OpenAI, Anthropic)
│   │   └── gitlab_client.py          # GitLab API client
│   ├── prompts/              # AI prompt templates and builders
│   └── utils/                # Utility functions
├── tests/                    # Test suite
├── deployment/               # Docker and deployment files
├── docs/                     # Documentation
└── pyproject.toml           # Project configuration
```

**Naming Convention:**
- **`*_service.py`**: Business logic layer, orchestrates multiple components
- **`*_client.py`**: External API integration layer (GitLab, databases, etc.)
- **`*_provider.py`**: Specific implementation of clients (OpenAI provider, Anthropic provider)

**Key Files:**
- **`orchestration_service.py`**: Handles both webhook and email triggers
- **`email_service.py`**: Email parsing, validation, and GitLab header extraction
- **`database_setup.py`**: Simple SQL-based table management (replaces Alembic)
- **`cli.py`**: Command-line interface for database and system management

## Monitoring and Logging

### Structured Logging
All logs are structured using structlog for better observability:

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "info",
  "logger": "orchestration_service",
  "message": "Analysis completed",
  "request_id": "req_123",
  "project_id": 456,
  "processing_time_ms": 1234
}
```

### Health Checks
- `/health` - Basic health check
- `/health/detailed` - Detailed component health

### Metrics (planned)
- Analysis success rate
- Processing time percentiles
- AI provider usage
- Cost tracking

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Run the test suite
6. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

- 📚 [Documentation](docs/)
- 🐛 [Issue Tracker](https://github.com/duongbinh/cicd-orchestrator/issues)
- 💬 [Discussions](https://github.com/duongbinh/cicd-orchestrator/discussions)
