import { queryOptions } from "@tanstack/react-query";
import {
  REGISTRY_CONTACT_ROLE_LABEL,
  REGISTRY_CONTACT_STATE_LABEL,
  REGISTRY_ORG_STATE_LABEL,
  REGISTRY_ORG_TYPE_LABEL,
  getRegistryContact,
  getRegistryMetrics,
  getRegistryOrganization,
  mockRegistryOrganizations,
} from "@/features/admin/mock-data/registry";
import type {
  RegistryContactRole,
  RegistryContactState,
  RegistryContact,
  RegistryOrgState,
  RegistryOrgType,
  RegistryOrganization,
} from "@/features/admin/mock-data/registry";

export {
  REGISTRY_CONTACT_ROLE_LABEL,
  REGISTRY_CONTACT_STATE_LABEL,
  REGISTRY_ORG_STATE_LABEL,
  REGISTRY_ORG_TYPE_LABEL,
  mockRegistryOrganizations,
};

export type {
  RegistryContact,
  RegistryContactRole,
  RegistryContactState,
  RegistryOrgState,
  RegistryOrgType,
  RegistryOrganization,
};

export const registryKeys = {
  all: () => ["admin", "registry"] as const,
  list: () => [...registryKeys.all(), "list"] as const,
  detail: (id: string) => [...registryKeys.all(), "detail", id] as const,
};

export function listOrganizations(): RegistryOrganization[] {
  return mockRegistryOrganizations;
}

export function getOrganization(id: string): RegistryOrganization | undefined {
  return getRegistryOrganization(id);
}

export function getContact(orgId: string, contactId: string): RegistryContact | undefined {
  return getRegistryContact(orgId, contactId);
}

export function getMetrics() {
  return getRegistryMetrics();
}

export { getRegistryContact, getRegistryMetrics, getRegistryOrganization };

export function registryListQueryOptions() {
  return queryOptions({
    queryKey: registryKeys.list(),
    queryFn: async () => listOrganizations(),
  });
}
