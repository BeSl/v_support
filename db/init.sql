CREATE TABLE IF NOT EXISTS sessions (
    session_id UUID PRIMARY KEY,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_activity TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_agent TEXT,
    ip_address TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    message_id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(session_id) ON DELETE CASCADE,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    role VARCHAR(10) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    context TEXT,
    sources TEXT
);

CREATE TABLE IF NOT EXISTS processing_stats (
    stat_id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_files INTEGER NOT NULL,
    processed_vectors INTEGER NOT NULL,
    errors INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS async_tasks (
    task_id UUID PRIMARY KEY,
    session_id UUID REFERENCES sessions(session_id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    status VARCHAR(20) NOT NULL CHECK (status IN ('pending', 'processing', 'completed', 'failed')) DEFAULT 'pending',
    username VARCHAR(255),
    user_id VARCHAR(255),
    question TEXT NOT NULL,
    answer TEXT,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_stats_timestamp ON processing_stats(timestamp);
CREATE INDEX IF NOT EXISTS idx_async_tasks_user ON async_tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_async_tasks_status ON async_tasks(status);
CREATE INDEX IF NOT EXISTS idx_async_tasks_created ON async_tasks(created_at);