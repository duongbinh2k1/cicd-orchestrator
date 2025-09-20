# CI/CD Orchestrator

An AI-powered CI/CD error analysis and remediation orchestrator that automatically analyzes failed pipelines and provides intelligent solutions.

## Features

- 🔗 **GitLab Integration**: Receives webhooks from GitLab for pipeline and job events
- 🤖 **AI-Powered Analysis**: Uses OpenAI, Anthropic, and other AI providers to analyze errors
- 📊 **Comprehensive Reporting**: Provides detailed error analysis with root cause and solutions
- 🚀 **FastAPI Backend**: Modern, async Python web framework
- 🐳 **Docker Support**: Containerized deployment with Docker Compose
- 📈 **Monitoring**: Built-in health checks and logging
- 🔐 **Security**: Webhook signature verification and secure configuration

## Quick Start

### Prerequisites

- Python 3.11+
- Docker and Docker Compose (optional)
- GitLab instance with API access
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

5. **Run database migrations**
```bash
alembic upgrade head
```

6. **Start the application**
```bash
# Development with auto-reload
uvicorn src.cicd_orchestrator.main:app --reload

# Development with host/port
uvicorn src.cicd_orchestrator.main:app --host 0.0.0.0 --port 8000 --reload

# Production
uvicorn src.cicd_orchestrator.main:app --host 0.0.0.0 --port 8000 --workers 4
```

7. **Verify installation**
```bash
# Check health endpoint
curl http://localhost:8000/health

# Test webhook endpoint
curl -X POST http://localhost:8000/test/webhook/custom \
  -H "Content-Type: application/json" \
  -d '{"project_id": 1001, "pipeline_status": "failed"}'
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

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `SECRET_KEY` | Application secret key | Yes | - |
| `GITLAB_API_TOKEN` | GitLab API token | Yes | - |
| `GITLAB_BASE_URL` | GitLab instance URL | No | https://gitlab.com |
| `GITLAB_WEBHOOK_SECRET` | Webhook secret for verification | No | - |
| `GITLAB_AUTO_FETCH_LOGS` | Auto-fetch logs from GitLab API | No | true |
| `GITLAB_FETCH_FULL_PIPELINE` | Fetch all jobs for context | No | true |
| `GITLAB_FETCH_TEST_REPORTS` | Fetch test reports | No | true |
| `GITLAB_MAX_LOG_SIZE_MB` | Max log size to download (MB) | No | 10 |
| `OPENAI_API_KEY` | OpenAI API key | No | - |
| `ANTHROPIC_API_KEY` | Anthropic API key | No | - |
| `DATABASE_URL` | Database connection URL | No | sqlite+aiosqlite:///./cicd_orchestrator.db |
| `REDIS_URL` | Redis connection URL | No | redis://localhost:6379/0 |
| `LOG_LEVEL` | Logging level | No | INFO |
| `ENVIRONMENT` | Environment (development/production) | No | development |

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

### GitLab Webhook Setup

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

### Enhanced Webhook Processing Flow
```
GitLab Webhook → FastAPI Handler → Async Background Task → GitLab Fetch → AI Analysis → Results
     (< 100ms)     (validation)     (non-blocking)       (logs/context)  (smart prompts)
                   (signature)       (error handling)     (test reports)  (solutions)
                   (normalization)   (retry logic)        (artifacts)     (prevention)
```

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│     GitLab      │───▶│  CI/CD Orchestr │───▶│   AI Provider   │
│   (Webhooks)    │    │      ator       │    │  (OpenAI/etc)   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
        │                        │                        │
        │                        ▼                        │
        │              ┌─────────────────┐                │
        │              │    Database     │                │
        │              │   (PostgreSQL)  │                │
        │              └─────────────────┘                │
        │                        │                        │
        │                        ▼                        │
        │              ┌─────────────────┐                │
        └──────────────│   Results       │◀───────────────┘
                       │   Storage       │
                       └─────────────────┘
```

### Key Benefits:
- **Fast Webhook Response**: Returns in < 100ms, preventing GitLab timeouts
- **Robust Async Processing**: Properly handled async background tasks with error recovery
- **Smart GitLab Integration**: Intelligent fetching strategy for logs and context
- **Enhanced Error Handling**: Comprehensive error catching and logging at all levels
- **Advanced AI Analysis**: Context-aware prompts with multiple AI provider support
- **Temporary Results Storage**: In-memory results cache with configurable retention
- **Webhook Testing Support**: Built-in endpoints for testing and validation
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
│   ├── core/                 # Configuration, logging, exceptions
│   ├── models/               # Pydantic models
│   ├── services/             # Business logic services & external clients
│   │   ├── orchestration_service.py  # Main business logic
│   │   ├── ai_service.py             # AI providers (OpenAI, Anthropic)
│   │   └── gitlab_client.py          # GitLab API client
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
