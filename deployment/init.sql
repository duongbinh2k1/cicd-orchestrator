-- Initialize database for CI/CD Orchestrator

-- Create extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Set timezone
SET timezone = 'UTC';

-- Create schemas
CREATE SCHEMA IF NOT EXISTS cicd;

-- Grant permissions
GRANT ALL PRIVILEGES ON SCHEMA cicd TO cicd_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA cicd TO cicd_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA cicd TO cicd_user;

-- Default permissions for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA cicd GRANT ALL PRIVILEGES ON TABLES TO cicd_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA cicd GRANT ALL PRIVILEGES ON SEQUENCES TO cicd_user;
