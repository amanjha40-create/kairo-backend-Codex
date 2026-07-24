import { queryOptions } from "@tanstack/react-query";
import {
  mockActivity,
  mockAdminMetrics,
  mockAttentionItems,
  mockFunnel,
  mockPlatformServices,
  mockVerificationStatuses,
} from "@/features/admin/mock-data";

export const overviewKeys = {
  all: () => ["admin", "overview"] as const,
  metrics: () => [...overviewKeys.all(), "metrics"] as const,
};

export const getMetrics = () => mockAdminMetrics;
export const getAttention = () => mockAttentionItems;
export const getFunnel = () => mockFunnel;
export const getStatuses = () => mockVerificationStatuses;
export const getActivity = () => mockActivity;
export const getServices = () => mockPlatformServices;

export function overviewMetricsQueryOptions() {
  return queryOptions({
    queryKey: overviewKeys.metrics(),
    queryFn: async () => getMetrics(),
  });
}
