import { queryOptions } from "@tanstack/react-query";
import {
  COMMUNICATION_CHANNEL_LABEL,
  COMMUNICATION_STATUS_LABEL,
  COMMUNICATION_TYPE_LABEL,
  DELIVERY_EVENT_LABEL,
  FAILURE_REASON_LABEL,
  FAILURE_RECOMMENDED_ACTION,
  getCommunication,
  getCommunicationMetrics,
  getCommunicationsForCase,
  getTemplate,
  isFailedStatus,
  mockCommunications,
  mockTemplates,
} from "@/features/admin/mock-data/communications";
import type {
  Communication,
  CommunicationChannel,
  CommunicationStatus,
  CommunicationType,
  DeliveryEvent,
  FollowUpRecord,
  InternalNoteSeed,
  TemplateDefinition,
  TemplateKey,
} from "@/features/admin/mock-data/communications";

export {
  COMMUNICATION_CHANNEL_LABEL,
  COMMUNICATION_STATUS_LABEL,
  COMMUNICATION_TYPE_LABEL,
  DELIVERY_EVENT_LABEL,
  FAILURE_REASON_LABEL,
  FAILURE_RECOMMENDED_ACTION,
  isFailedStatus,
  mockCommunications,
  mockTemplates,
};

export type {
  Communication,
  CommunicationChannel,
  CommunicationStatus,
  CommunicationType,
  DeliveryEvent,
  FollowUpRecord,
  InternalNoteSeed,
  TemplateDefinition,
  TemplateKey,
};

export const communicationKeys = {
  all: () => ["admin", "communications"] as const,
  list: () => [...communicationKeys.all(), "list"] as const,
  detail: (id: string) => [...communicationKeys.all(), "detail", id] as const,
  metrics: () => [...communicationKeys.all(), "metrics"] as const,
};

export function listCommunications(): Communication[] {
  return mockCommunications;
}

export function getCommunicationById(id: string): Communication | undefined {
  return getCommunication(id);
}

export function listCommunicationsForCase(caseId: string): Communication[] {
  return getCommunicationsForCase(caseId);
}

export function getMetrics() {
  return getCommunicationMetrics();
}

export { getCommunication, getCommunicationMetrics, getCommunicationsForCase, getTemplate };

export function communicationsListQueryOptions() {
  return queryOptions({
    queryKey: communicationKeys.list(),
    queryFn: async () => listCommunications(),
  });
}
