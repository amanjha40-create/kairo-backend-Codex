import { queryOptions } from "@tanstack/react-query";
import {
  ALL_INVESTIGATORS,
  DOCUMENT_ANOMALY_LABEL,
  EVENT_KIND_LABEL,
  INVESTIGATION_STATUS_LABEL,
  NOTE_CATEGORY_LABEL,
  RESOLVED_STATUSES,
  RECOMMENDED_ACTION_LABEL,
  RISK_CATEGORY_LABEL,
  RISK_LEVEL_LABEL,
  SIGNAL_CONFIDENCE_LABEL,
  SIGNAL_SEVERITY_LABEL,
  SIGNAL_SOURCE_LABEL,
  SIGNAL_STATUS_LABEL,
  SUBJECT_KIND_LABEL,
  getInvestigation,
  getRiskMetrics,
  mockInvestigations,
} from "@/features/admin/mock-data/risk";
import type {
  DocumentAnomaly,
  DuplicateReview,
  Investigation,
  InvestigationEventKind,
  InvestigationNote,
  InvestigationStatus,
  InvestigationTimelineEvent,
  NoteCategory,
  RecommendedActionKind,
  RiskCategory,
  RiskLevel,
  RiskMetrics,
  RiskSignal,
  SubjectKind,
} from "@/features/admin/mock-data/risk";

export {
  ALL_INVESTIGATORS,
  DOCUMENT_ANOMALY_LABEL,
  EVENT_KIND_LABEL,
  INVESTIGATION_STATUS_LABEL,
  NOTE_CATEGORY_LABEL,
  RESOLVED_STATUSES,
  RECOMMENDED_ACTION_LABEL,
  RISK_CATEGORY_LABEL,
  RISK_LEVEL_LABEL,
  SIGNAL_CONFIDENCE_LABEL,
  SIGNAL_SEVERITY_LABEL,
  SIGNAL_SOURCE_LABEL,
  SIGNAL_STATUS_LABEL,
  SUBJECT_KIND_LABEL,
  mockInvestigations,
};

export type { Investigation, RiskMetrics };
export type {
  DocumentAnomaly,
  DuplicateReview,
  InvestigationEventKind,
  InvestigationNote,
  InvestigationStatus,
  InvestigationTimelineEvent,
  NoteCategory,
  RecommendedActionKind,
  RiskCategory,
  RiskLevel,
  RiskSignal,
  SubjectKind,
};

export const riskKeys = {
  all: () => ["admin", "risk"] as const,
  list: () => [...riskKeys.all(), "list"] as const,
  detail: (id: string) => [...riskKeys.all(), "detail", id] as const,
};

export function listInvestigations(): Investigation[] {
  return mockInvestigations;
}

export function getInvestigationById(id: string): Investigation | undefined {
  return getInvestigation(id);
}

export function getMetrics(): RiskMetrics {
  return getRiskMetrics();
}

export { getInvestigation, getRiskMetrics };

export function riskListQueryOptions() {
  return queryOptions({
    queryKey: riskKeys.list(),
    queryFn: async () => listInvestigations(),
  });
}
