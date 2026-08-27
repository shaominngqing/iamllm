CREATE TABLE IF NOT EXISTS human_requests (
    id TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    messages_json TEXT NOT NULL,
    preview TEXT NOT NULL DEFAULT '',
    context_chars INTEGER NOT NULL DEFAULT 0,
    message_count INTEGER NOT NULL DEFAULT 0,
    system_count INTEGER NOT NULL DEFAULT 0,
    tool_count INTEGER NOT NULL DEFAULT 0,
    attachment_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('pending', 'answered', 'expired')),
    answer TEXT,
    mode TEXT NOT NULL CHECK (mode IN ('sync', 'async')),
    created_at INTEGER NOT NULL,
    answered_at INTEGER,
    expires_at INTEGER NOT NULL,
    conversation_id TEXT,
    tools_json TEXT NOT NULL DEFAULT '[]',
    response_json TEXT,
    source TEXT NOT NULL DEFAULT 'api',
    updated_at INTEGER NOT NULL DEFAULT 0,
    auto_reply_rule_id TEXT,
    auto_reply_due_at INTEGER,
    auto_reply_label TEXT,
    auto_reply_text TEXT,
    answer_source TEXT,
    stream_requested INTEGER NOT NULL DEFAULT 0,
    stream_chunk_count INTEGER NOT NULL DEFAULT 0,
    claim_owner TEXT,
    claim_expires_at INTEGER,
    client_last_seen_at INTEGER,
    api_key_id TEXT,
    read_at INTEGER,
    draft_text TEXT,
    draft_updated_at INTEGER,
    draft_device_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_human_requests_status_created
ON human_requests(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_human_requests_unread
ON human_requests(status, read_at, created_at DESC);

CREATE TABLE IF NOT EXISTS human_stream_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    chunk_id TEXT,
    content TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    UNIQUE(request_id, position),
    FOREIGN KEY (request_id) REFERENCES human_requests(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_human_stream_chunks_request
ON human_stream_chunks(request_id, position);

CREATE UNIQUE INDEX IF NOT EXISTS idx_human_stream_chunks_chunk_id
ON human_stream_chunks(request_id, chunk_id)
WHERE chunk_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    owner_hash TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content_json TEXT,
    tool_call_id TEXT,
    tool_calls_json TEXT,
    request_id TEXT UNIQUE,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_order
ON conversation_messages(conversation_id, created_at, id);

CREATE TABLE IF NOT EXISTS model_profile (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    display_name TEXT NOT NULL,
    bio TEXT NOT NULL,
    skills_json TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS quick_replies (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    category TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS auto_reply_rules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    rule_type TEXT NOT NULL CHECK (rule_type IN ('keyword', 'schedule')),
    match_type TEXT CHECK (match_type IN ('contains', 'exact') OR match_type IS NULL),
    pattern TEXT,
    response_text TEXT NOT NULL,
    start_time TEXT,
    end_time TEXT,
    days_json TEXT NOT NULL DEFAULT '[0,1,2,3,4,5,6]',
    delay_seconds INTEGER NOT NULL DEFAULT 0,
    priority INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    key_hint TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 1,
    rate_limit_per_minute INTEGER NOT NULL DEFAULT 10,
    daily_limit INTEGER NOT NULL DEFAULT 100,
    max_concurrent INTEGER NOT NULL DEFAULT 3,
    request_count INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    last_used_at INTEGER,
    revoked_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_api_keys_active
ON api_keys(active, created_at DESC);

CREATE TABLE IF NOT EXISTS api_key_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (api_key_id) REFERENCES api_keys(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_api_key_calls_window
ON api_key_calls(api_key_id, created_at);

CREATE TABLE IF NOT EXISTS admin_devices (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'unknown',
    refresh_hash TEXT NOT NULL UNIQUE,
    device_model TEXT,
    os_version TEXT,
    app_version TEXT,
    locale TEXT,
    timezone TEXT,
    ip_address TEXT,
    user_agent TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    last_seen_at INTEGER,
    revoked_at INTEGER
);

CREATE TABLE IF NOT EXISTS pairing_codes (
    code_hash TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    used_at INTEGER
);

CREATE TABLE IF NOT EXISTS admin_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    resource_id TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_admin_events_created
ON admin_events(id, created_at);

CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);

INSERT OR IGNORE INTO app_meta(key, value) VALUES ('queue_version', 1);

INSERT OR IGNORE INTO model_profile(
    singleton_id, display_name, bio, skills_json, updated_at
) VALUES (1, 'Human Model', 'A human-operated language model.', '[]', 0);
