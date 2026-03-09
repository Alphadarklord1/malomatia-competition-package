PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
  version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
  case_id TEXT PRIMARY KEY,
  request_text_ar TEXT NOT NULL,
  request_text_en TEXT NOT NULL,
  intent_ar TEXT NOT NULL,
  intent_en TEXT NOT NULL,
  urgency_ar TEXT NOT NULL,
  urgency_en TEXT NOT NULL,
  department_ar TEXT NOT NULL,
  department_en TEXT NOT NULL,
  confidence REAL NOT NULL,
  reason_ar TEXT NOT NULL,
  reason_en TEXT NOT NULL,
  detected_keywords_ar TEXT NOT NULL,
  detected_keywords_en TEXT NOT NULL,
  detected_time_ar TEXT NOT NULL,
  detected_time_en TEXT NOT NULL,
  policy_rule TEXT NOT NULL,
  status_ar TEXT NOT NULL,
  status_en TEXT NOT NULL,
  state TEXT NOT NULL,
  assigned_team TEXT,
  assigned_user TEXT,
  sla_deadline_utc TEXT NOT NULL,
  created_at_utc TEXT NOT NULL,
  triaged_at_utc TEXT,
  assigned_at_utc TEXT,
  resolved_at_utc TEXT,
  closed_at_utc TEXT,
  updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_events (
  event_id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  actor_user_id TEXT NOT NULL,
  actor_role TEXT NOT NULL,
  event_type TEXT NOT NULL,
  from_state TEXT,
  to_state TEXT,
  reason TEXT,
  timestamp_utc TEXT NOT NULL,
  meta_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY(case_id) REFERENCES cases(case_id)
);

CREATE TABLE IF NOT EXISTS saved_views (
  view_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  name TEXT NOT NULL,
  filters_json TEXT NOT NULL,
  is_default INTEGER NOT NULL DEFAULT 0,
  created_at_utc TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
  notification_id TEXT PRIMARY KEY,
  case_id TEXT,
  severity TEXT NOT NULL,
  type TEXT NOT NULL,
  message_ar TEXT NOT NULL,
  message_en TEXT NOT NULL,
  ack_by_user TEXT,
  ack_at_utc TEXT,
  created_at_utc TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  auth_provider TEXT NOT NULL DEFAULT 'local',
  role TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  mfa_required INTEGER NOT NULL DEFAULT 0,
  mfa_type TEXT NOT NULL DEFAULT 'none',
  totp_secret TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  failed_attempts INTEGER NOT NULL DEFAULT 0,
  locked_until_utc TEXT,
  password_changed_at_utc TEXT NOT NULL,
  last_login_at_utc TEXT,
  created_at_utc TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cases_state ON cases(state);
CREATE INDEX IF NOT EXISTS idx_cases_department ON cases(department_en);
CREATE INDEX IF NOT EXISTS idx_cases_assigned_user ON cases(assigned_user);
CREATE INDEX IF NOT EXISTS idx_cases_sla_deadline ON cases(sla_deadline_utc);

CREATE INDEX IF NOT EXISTS idx_events_case_id ON workflow_events(case_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON workflow_events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON workflow_events(timestamp_utc);

CREATE UNIQUE INDEX IF NOT EXISTS idx_saved_views_user_name ON saved_views(user_id, name);
CREATE INDEX IF NOT EXISTS idx_saved_views_user_default ON saved_views(user_id, is_default);

CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications(type);
CREATE INDEX IF NOT EXISTS idx_notifications_case ON notifications(case_id);
CREATE INDEX IF NOT EXISTS idx_notifications_ack ON notifications(ack_at_utc);
CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at_utc);
CREATE UNIQUE INDEX IF NOT EXISTS idx_notifications_unique_key ON notifications(type, case_id);

CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);
CREATE INDEX IF NOT EXISTS idx_users_provider ON users(auth_provider);
