import { queryOptions } from "@tanstack/react-query";
import {
  ALL_ASSIGNEES,
  ATTENTION_FLAG_LABEL,
  COMPLETED_STATUSES,
  ORGANIZATION_STATUS_LABEL,
  SLA_LABEL,
  VERIFICATION_TYPE_LABEL,
  mockVerificationCases,
} from "@/features/admin/mock-data/verification-cases";
import type {
  Assignee,
  AttentionFlag,
  OrganizationStatus,
  SlaState,
  VerificationCase,
  VerificationType,
} from "@/features/admin/mock-data/verification-cases";

export {
  ALL_ASSIGNEES,
  ATTENTION_FLAG_LABEL,
  COMPLETED_STATUSES,
  ORGANIZATION_STATUS_LABEL,
  SLA_LABEL,
  VERIFICATION_TYPE_LABEL,
  mockVerificationCases,
};

export type {
  Assignee,
  AttentionFlag,
  OrganizationStatus,
  SlaState,
  VerificationCase,
  VerificationType,
};

export const verificationKeys = {
  all: () => ["admin", "verifications"] as const,
  list: () => [...verificationKeys.all(), "list"] as const,
  detail: (caseId: string) => [...verificationKeys.all(), "detail", caseId] as const,
};

export function listCases(): VerificationCase[] {
  return mockVerificationCases;
}

export function getCaseById(caseId: string): VerificationCase | undefined {
  return mockVerificationCases.find((caseRecord) => caseRecord.id === caseId);
}

export function getCaseByReference(reference: string): VerificationCase | undefined {
  return mockVerificationCases.find((caseRecord) => caseRecord.reference === reference);
}

export function verificationListQueryOptions() {
  return queryOptions({
    queryKey: verificationKeys.list(),
    queryFn: async () => listCases(),
  });
}
