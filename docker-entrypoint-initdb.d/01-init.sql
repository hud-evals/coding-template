-- Database initialization for PostgreSQL
-- CUSTOMIZE THIS FILE for your database setup

-- Create database user
CREATE USER [DB_USER] WITH SUPERUSER PASSWORD '[DB_PASSWORD]';
CREATE DATABASE [DB_USER];
GRANT ALL PRIVILEGES ON DATABASE [DB_USER] TO [DB_USER];

-- Create development database
CREATE DATABASE [PROJECT_NAME]_development;
GRANT ALL PRIVILEGES ON DATABASE [PROJECT_NAME]_development TO [DB_USER];

-- Create test database
CREATE DATABASE [PROJECT_NAME]_test;
GRANT ALL PRIVILEGES ON DATABASE [PROJECT_NAME]_test TO [DB_USER];

-- Additional setup (optional)
-- CREATE EXTENSION IF NOT EXISTS vector;  -- For pgvector
-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";  -- For UUIDs
