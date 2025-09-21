-- Initialize database for CI/CD Orchestrator (Oracle version)
-- This file is for reference only since we're using external Oracle DB

-- Set session timezone (Oracle syntax)
-- ALTER SESSION SET TIME_ZONE = 'UTC';

-- Create user and grant permissions (if needed)
-- Note: Assuming user 'svs' already exists with proper permissions

-- Grant necessary privileges to svs user
-- GRANT CREATE TABLE, CREATE SEQUENCE, CREATE INDEX TO svs;
-- GRANT CREATE SESSION TO svs;
-- GRANT UNLIMITED TABLESPACE TO svs;

-- Example of creating tablespace (if needed)
-- CREATE TABLESPACE cicd_data
-- DATAFILE 'cicd_data.dbf' SIZE 100M
-- AUTOEXTEND ON NEXT 10M MAXSIZE 1G;
