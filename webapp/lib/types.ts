export type AuthUser = {
  accessToken: string;
  role: string;
  userId: string;
  displayName: string;
  authProvider: string;
};

export type DashboardSummary = {
  open_cases: number;
  sla_at_risk: number;
  escalated_cases: number;
  override_count: number;
  by_department: Array<{ department: string; count: number }>;
};

export type CaseSummary = {
  case_id: string;
  request_text: string;
  intent: string;
  urgency: string;
  department: string;
  confidence: number;
  state: string;
  assigned_team: string | null;
  assigned_user: string | null;
  sla_status: string;
  sla_deadline_utc: string;
  updated_at_utc: string;
};

export type CaseExplanation = {
  reason_ar: string;
  reason_en: string;
  detected_keywords_ar: string;
  detected_keywords_en: string;
  detected_time_ar: string;
  detected_time_en: string;
  policy_rule: string;
};

export type CaseDetail = {
  case_id: string;
  request_text_ar: string;
  request_text_en: string;
  intent_ar: string;
  intent_en: string;
  urgency_ar: string;
  urgency_en: string;
  department_ar: string;
  department_en: string;
  confidence: number;
  state: string;
  assigned_team: string | null;
  assigned_user: string | null;
  status_ar: string;
  status_en: string;
  explanation: CaseExplanation;
  sla_status: string;
  sla_deadline_utc: string;
  created_at_utc: string;
  updated_at_utc: string;
};

export type CaseActionResult = {
  message: string;
  case: CaseDetail;
};

export type TimelineEvent = {
  source: string;
  event_type: string;
  actor_user_id: string;
  actor_role: string;
  timestamp_utc: string;
  from_state?: string | null;
  to_state?: string | null;
  result?: string | null;
  reason?: string | null;
  details: Record<string, unknown>;
};

export type PaginatedCases = {
  items: CaseSummary[];
  page: number;
  page_size: number;
  total: number;
};

export type ReviewCase = {
  case: CaseSummary;
  review_flags: string[];
  latest_override_at?: string | null;
};

export type ReviewSummary = {
  escalated: ReviewCase[];
  low_confidence: ReviewCase[];
  recently_overridden: ReviewCase[];
};

export type NotificationItem = {
  notification_id: string;
  case_id?: string | null;
  category: string;
  severity: string;
  title: string;
  message: string;
  ack_by_user?: string | null;
  ack_at_utc?: string | null;
  created_at_utc: string;
  updated_at_utc: string;
};

export type NotificationsResponse = {
  items: NotificationItem[];
};

export type RagHit = {
  rank: number;
  doc_id: string;
  chunk_id: string;
  title: string;
  department: string;
  policy_rule: string;
  text: string;
  base_score: number;
  rerank_score: number;
  keyword_hits: string[];
  reasons: string[];
};

export type RagResponse = {
  answer: string;
  hits: RagHit[];
  used_llm: boolean;
  insufficient_evidence: boolean;
  policy_blocked: boolean;
  llm_error?: string | null;
};
