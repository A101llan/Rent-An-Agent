-- Enable extensions for future pgvector support
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- pgvector will be enabled in a future migration:
-- CREATE EXTENSION IF NOT EXISTS vector;
