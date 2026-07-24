import { queryOptions } from "@tanstack/react-query";
import {
  ALERT_KIND_LABEL,
  ALERT_SEVERITY_LABEL,
  ALERT_STATUS_LABEL,
  AUDIT_RESOURCE_LABEL,
  FLAG_STATE_LABEL,
  JOB_STATUS_LABEL,
  JOB_TYPE_LABEL,
  MESSAGE_KIND_LABEL,
  MESSAGE_STATUS_LABEL,
  SERVICE_HEALTH_LABEL,
  getJobById,
  getSystemOverviewMetrics,
  mockAlerts,
  mockAuditEvents,
  mockBackgroundJobs,
  mockConfigReference,
  mockDeployments,
  mockFeatureFlags,
  mockMessageLogs,
  mockPlatformServices,
} from "@/features/admin/mock-data/system";
import type {
  AlertRecord,
  AlertStatus,
  AuditEvent,
  BackgroundJob,
  ConfigEntry,
  Deployment,
  FeatureFlag,
  FlagState,
  JobStatus,
  JobType,
  MessageChannel,
  MessageKind,
  MessageLog,
  MessageStatus,
  PlatformService,
  ServiceHealthState,
  SystemOverviewMetrics,
} from "@/features/admin/mock-data/system";

export {
  ALERT_KIND_LABEL,
  ALERT_SEVERITY_LABEL,
  ALERT_STATUS_LABEL,
  AUDIT_RESOURCE_LABEL,
  FLAG_STATE_LABEL,
  JOB_STATUS_LABEL,
  JOB_TYPE_LABEL,
  MESSAGE_KIND_LABEL,
  MESSAGE_STATUS_LABEL,
  SERVICE_HEALTH_LABEL,
  mockAlerts,
  mockAuditEvents,
  mockBackgroundJobs,
  mockConfigReference,
  mockDeployments,
  mockFeatureFlags,
  mockMessageLogs,
  mockPlatformServices,
};

export type {
  AlertRecord,
  AlertStatus,
  AuditEvent,
  BackgroundJob,
  ConfigEntry,
  Deployment,
  FeatureFlag,
  FlagState,
  JobStatus,
  JobType,
  MessageChannel,
  MessageKind,
  MessageLog,
  MessageStatus,
  PlatformService,
  ServiceHealthState,
  SystemOverviewMetrics,
};

export const systemKeys = {
  all: () => ["admin", "system"] as const,
  overview: () => [...systemKeys.all(), "overview"] as const,
};

export const listServices = (): PlatformService[] => mockPlatformServices;
export const listJobs = (): BackgroundJob[] => mockBackgroundJobs;
export const getJob = (id: string): BackgroundJob | undefined => getJobById(id);
export const listFlags = (): FeatureFlag[] => mockFeatureFlags;
export const listMessageLogs = (): MessageLog[] => mockMessageLogs;
export const listAuditEvents = (): AuditEvent[] => mockAuditEvents;
export const listAlerts = (): AlertRecord[] => mockAlerts;
export const listDeployments = (): Deployment[] => mockDeployments;
export const listConfigReference = (): ConfigEntry[] => mockConfigReference;
export const getOverviewMetrics = (): SystemOverviewMetrics => getSystemOverviewMetrics();

export { getJobById, getSystemOverviewMetrics };

export function systemOverviewQueryOptions() {
  return queryOptions({
    queryKey: systemKeys.overview(),
    queryFn: async () => getOverviewMetrics(),
  });
}
