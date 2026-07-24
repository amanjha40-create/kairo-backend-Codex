import { queryOptions } from "@tanstack/react-query";
import {
  ACCOUNT_STATUS_LABEL,
  ATTENTION_LABEL,
  ONBOARDING_STEP_LABEL,
  ONBOARDING_STEP_ORDER,
  PASSPORT_STATUS_LABEL,
  PROFILE_TYPE_LABEL,
  TRUST_BAND_LABEL,
  getUser,
  getUserDirectoryMetrics,
  initialsFor,
  mockUsers,
} from "@/features/admin/mock-data/users";
import type {
  PassportStatus,
  ProfileType,
  UserAccountStatus,
  UserActivityEvent,
  UserAttentionKind,
  UserDirectoryMetrics,
  UserRecord,
} from "@/features/admin/mock-data/users";

export {
  ACCOUNT_STATUS_LABEL,
  ATTENTION_LABEL,
  ONBOARDING_STEP_LABEL,
  ONBOARDING_STEP_ORDER,
  PASSPORT_STATUS_LABEL,
  PROFILE_TYPE_LABEL,
  TRUST_BAND_LABEL,
  initialsFor,
  mockUsers,
};

export type {
  PassportStatus,
  ProfileType,
  UserAccountStatus,
  UserActivityEvent,
  UserAttentionKind,
  UserDirectoryMetrics,
  UserRecord,
};

export const userKeys = {
  all: () => ["admin", "users"] as const,
  list: () => [...userKeys.all(), "list"] as const,
  detail: (id: string) => [...userKeys.all(), "detail", id] as const,
};

export function listUsers(): UserRecord[] {
  return mockUsers;
}

export function getUserById(id: string): UserRecord | undefined {
  return getUser(id);
}

export function getDirectoryMetrics(): UserDirectoryMetrics {
  return getUserDirectoryMetrics();
}

export { getUser, getUserDirectoryMetrics };

export function userListQueryOptions() {
  return queryOptions({
    queryKey: userKeys.list(),
    queryFn: async () => listUsers(),
  });
}
