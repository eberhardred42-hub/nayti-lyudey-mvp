-- Stage 9.3.2: artifact_files
-- Stores binary blobs in S3-compatible storage; Postgres keeps metadata + object key.

CREATE TABLE IF NOT EXISTS artifacts (
  id UUID PRIMARY KEY,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS artifact_files (
  id UUID PRIMARY KEY,
  artifact_id UUID NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
  storage TEXT NOT NULL DEFAULT 's3',
  bucket TEXT NOT NULL,
  object_key TEXT NOT NULL,
  content_type TEXT NOT NULL,
  size_bytes BIGINT NULL,
  etag TEXT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_artifact_files_artifact_id
  ON artifact_files(artifact_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_artifact_files_bucket_object_key
  ON artifact_files(bucket, object_key);
