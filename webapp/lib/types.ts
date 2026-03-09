export type QueueStatus = "ON_TRACK" | "AT_RISK" | "BREACHED";

export type CaseRecord = {
  caseId: string;
  request: string;
  intent: string;
  urgency: string;
  department: string;
  confidence: number;
  state: string;
  slaStatus: QueueStatus;
};
