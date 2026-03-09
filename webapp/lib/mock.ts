import type { CaseRecord } from "./types";

export const mockCases: CaseRecord[] = [
  {
    caseId: "CASE-001",
    request: "اقامتي تنتهي غداً وأحتاج تجديداً عاجلاً",
    intent: "Residency Renewal",
    urgency: "Urgent",
    department: "Immigration",
    confidence: 0.82,
    state: "ESCALATED",
    slaStatus: "AT_RISK",
  },
  {
    caseId: "CASE-002",
    request: "Request for a new commercial shop license in the industrial area",
    intent: "Commercial License Issuance",
    urgency: "Warning",
    department: "Licensing",
    confidence: 0.76,
    state: "TRIAGED",
    slaStatus: "ON_TRACK",
  },
];
