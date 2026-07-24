import { queryOptions } from "@tanstack/react-query";
import {
  CLAIM_SOURCE_LABEL,
  COMMUNICATION_STATE_LABEL,
  CONTACT_SOURCE_LABEL,
  CONTACT_STATE_LABEL,
  CORRECTION_STATE_LABEL,
  EVIDENCE_DOC_LABEL,
  NOTE_CATEGORY_LABEL,
  PRIORITY_LABEL,
  formatFileSize,
  getVerificationCaseDetail,
} from "@/features/admin/mock-data/case-details";
import type {
  AttentionFlagRecord,
  CaseTimelineEvent,
  ComparisonResult,
  EvidenceItem,
  EvidenceProcessingState,
  EvidenceReviewState,
  InternalNote,
  NoteCategory,
  OrganizationSuggestion,
  TimelineEventKind,
  VerificationCaseDetail,
  VerificationContact,
} from "@/features/admin/mock-data/case-details";

export {
  CLAIM_SOURCE_LABEL,
  COMMUNICATION_STATE_LABEL,
  CONTACT_SOURCE_LABEL,
  CONTACT_STATE_LABEL,
  CORRECTION_STATE_LABEL,
  EVIDENCE_DOC_LABEL,
  NOTE_CATEGORY_LABEL,
  PRIORITY_LABEL,
  formatFileSize,
};

export type {
  AttentionFlagRecord,
  CaseTimelineEvent,
  ComparisonResult,
  EvidenceItem,
  EvidenceProcessingState,
  EvidenceReviewState,
  InternalNote,
  NoteCategory,
  OrganizationSuggestion,
  TimelineEventKind,
  VerificationCaseDetail,
  VerificationContact,
};

export const caseKeys = {
  all: () => ["admin", "cases"] as const,
  detail: (caseId: string) => [...caseKeys.all(), "detail", caseId] as const,
};

export function getCase(caseId: string): VerificationCaseDetail | undefined {
  return getVerificationCaseDetail(caseId);
}

export { getVerificationCaseDetail };

export function caseDetailQueryOptions(caseId: string) {
  return queryOptions({
    queryKey: caseKeys.detail(caseId),
    queryFn: async () => getCase(caseId),
  });
}
