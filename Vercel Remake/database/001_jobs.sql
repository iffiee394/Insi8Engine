CREATE TABLE IF NOT EXISTS knowledge_jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'process_video',
    video_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    locked_at TIMESTAMPTZ,
    locked_by TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS knowledge_jobs_status_created_idx
    ON knowledge_jobs(status, created_at);

CREATE INDEX IF NOT EXISTS knowledge_jobs_video_idx
    ON knowledge_jobs(video_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS knowledge_jobs_one_active_process_per_video_idx
    ON knowledge_jobs(video_id, kind)
    WHERE status IN ('queued', 'running') AND kind = 'process_video';
