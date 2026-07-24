/**
 * Kairo Admin — Registry mock data.
 *
 * Deterministic seed data for the Organization Registry used by both the
 * `/admin/registry` list page and each Case Workspace's organization
 * resolution panel. IDs align with `verification-cases.ts` so an org
 * shown on a case can be opened in the Registry.
 *
 * BACKEND INTEGRATION NOTE
 * ------------------------
 * Replace `mockRegistryOrganizations` + accessors with real Query hooks
 * when the Registry API is available. Do NOT keep falling back to mock
 * data at that point — surface loading/empty/error states instead.
 */

import type { AttentionFlag } from "./verification-cases";

// --- Frozen NOW (hour-aligned) ---
const NOW = new Date(Math.floor(Date.now() / 3_600_000) * 3_600_000);
function ago(days: number, hours = 0): string {
  const d = new Date(NOW);
  d.setUTCHours(d.getUTCHours() - hours);
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString();
}

// =====================================================================
// Types
// =====================================================================

export type RegistryOrgState = "verified" | "unverified" | "duplicate_review" | "deprecated";

export const REGISTRY_ORG_STATE_LABEL: Record<RegistryOrgState, string> = {
  verified: "Verified in registry",
  unverified: "Unverified",
  duplicate_review: "Duplicate review",
  deprecated: "Deprecated",
};

export type RegistryOrgType =
  | "private_company"
  | "public_company"
  | "non_profit"
  | "government"
  | "educational_institution"
  | "certification_body"
  | "platform";

export const REGISTRY_ORG_TYPE_LABEL: Record<RegistryOrgType, string> = {
  private_company: "Private company",
  public_company: "Public company",
  non_profit: "Non-profit",
  government: "Government",
  educational_institution: "Educational institution",
  certification_body: "Certification body",
  platform: "Platform",
};

export type RegistryContactState =
  "approved" | "unverified" | "bounced" | "inactive" | "rejected" | "needs_review";

export const REGISTRY_CONTACT_STATE_LABEL: Record<RegistryContactState, string> = {
  approved: "Approved",
  unverified: "Unverified",
  bounced: "Bounced",
  inactive: "Inactive",
  rejected: "Rejected",
  needs_review: "Needs review",
};

export type RegistryContactRole =
  | "hr"
  | "people_ops"
  | "manager"
  | "compliance"
  | "shared_inbox"
  | "registrar"
  | "issuer"
  | "other";

export const REGISTRY_CONTACT_ROLE_LABEL: Record<RegistryContactRole, string> = {
  hr: "HR",
  people_ops: "People Operations",
  manager: "Direct manager",
  compliance: "Compliance",
  shared_inbox: "Shared inbox",
  registrar: "Registrar",
  issuer: "Credential issuer",
  other: "Other",
};

export interface RegistryContact {
  id: string;
  name: string;
  role: RegistryContactRole;
  jobTitle: string;
  emailMasked: string;
  phoneMasked?: string;
  state: RegistryContactState;
  confidence: number;
  bounceCount: number;
  addedBy: string;
  addedAt: string;
  lastSuccessfulUse?: string;
  notes?: string;
  /** Session-only flag for contacts added or edited in the current browser session. */
  sessionOnly?: boolean;
}

export interface RegistryActivityEvent {
  id: string;
  at: string;
  kind:
    | "created"
    | "contact_added"
    | "contact_approved"
    | "contact_bounced"
    | "duplicate_flagged"
    | "org_merged"
    | "outreach_sent"
    | "outreach_response"
    | "note_added";
  actor: string;
  description: string;
  sessionOnly?: boolean;
}

export interface RegistryOrganization {
  id: string;
  canonicalName: string;
  aliases: string[];
  state: RegistryOrgState;
  orgType: RegistryOrgType;
  domain: string;
  website: string;
  country: string;
  headquartersCity?: string;
  yearFounded?: number;
  employeesRange?: string;
  description?: string;
  createdAt: string;
  updatedAt: string;
  createdBy: string;
  contacts: RegistryContact[];
  activity: RegistryActivityEvent[];
  activeCaseCount: number;
  totalVerifications: number;
  duplicateOfId?: string;
  possibleDuplicateIds: string[];
  /** Session-only flag for orgs proposed during the current browser session. */
  sessionOnly?: boolean;
  /** Attention flags surfaced at the org level. */
  registryFlags: AttentionFlag[];
}

// =====================================================================
// Deterministic seed data
// =====================================================================

function slug(name: string) {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "");
}
function mask(local: string, domain: string) {
  const shown = local.slice(0, 1);
  const rest = local.length > 1 ? "•".repeat(Math.max(2, local.length - 1)) : "";
  return `${shown}${rest}@${domain}`;
}

interface OrgSeed {
  id: string;
  name: string;
  aliases?: string[];
  state: RegistryOrgState;
  orgType: RegistryOrgType;
  country: string;
  city?: string;
  founded?: number;
  employees?: string;
  contacts?: number;
  activeCases: number;
  totalVerifications: number;
  duplicateOf?: string;
  possibleDuplicates?: string[];
  registryFlags?: AttentionFlag[];
  description?: string;
}

const SEEDS: OrgSeed[] = [
  {
    id: "org-11",
    name: "Northwind Analytics",
    aliases: ["Northwind Analytics GmbH"],
    state: "verified",
    orgType: "private_company",
    country: "Germany",
    city: "Berlin",
    founded: 2014,
    employees: "201–500",
    activeCases: 3,
    totalVerifications: 42,
  },
  {
    id: "org-12",
    name: "Globex Ltd",
    state: "verified",
    orgType: "private_company",
    country: "United Kingdom",
    city: "London",
    founded: 2009,
    employees: "1001–5000",
    activeCases: 2,
    totalVerifications: 88,
  },
  {
    id: "org-13",
    name: "Acme Corp",
    state: "verified",
    orgType: "public_company",
    country: "United States",
    city: "New York",
    founded: 1971,
    employees: "5001+",
    activeCases: 5,
    totalVerifications: 214,
  },
  {
    id: "org-14",
    name: "Umbrella GmbH",
    aliases: ["Umbrella Corporation DE"],
    state: "duplicate_review",
    orgType: "private_company",
    country: "Germany",
    city: "Frankfurt",
    founded: 2018,
    employees: "51–200",
    activeCases: 1,
    totalVerifications: 12,
    possibleDuplicates: ["org-14b"],
    registryFlags: ["possible_duplicate"],
  },
  {
    id: "org-14b",
    name: "Umbrella Deutschland GmbH",
    state: "unverified",
    orgType: "private_company",
    country: "Germany",
    city: "Frankfurt",
    founded: 2019,
    employees: "51–200",
    contacts: 0,
    activeCases: 0,
    totalVerifications: 0,
    possibleDuplicates: ["org-14"],
    registryFlags: ["possible_duplicate"],
  },
  {
    id: "org-15",
    name: "Initech LLC",
    state: "unverified",
    orgType: "private_company",
    country: "United States",
    city: "Austin",
    founded: 2016,
    employees: "11–50",
    contacts: 1,
    activeCases: 1,
    totalVerifications: 4,
  },
  {
    id: "org-16",
    name: "Wayne Industries",
    state: "verified",
    orgType: "public_company",
    country: "United States",
    city: "Gotham",
    founded: 1939,
    employees: "5001+",
    activeCases: 4,
    totalVerifications: 156,
  },
  {
    id: "org-17",
    name: "AWS Certified Programs",
    state: "verified",
    orgType: "certification_body",
    country: "United States",
    city: "Seattle",
    founded: 2013,
    employees: "5001+",
    activeCases: 6,
    totalVerifications: 402,
  },
  {
    id: "org-18",
    name: "Stark Industries",
    state: "verified",
    orgType: "public_company",
    country: "United States",
    city: "Malibu",
    founded: 1940,
    employees: "5001+",
    activeCases: 3,
    totalVerifications: 71,
    registryFlags: ["email_bounced"],
  },
  {
    id: "org-19",
    name: "Cyberdyne Systems",
    state: "verified",
    orgType: "private_company",
    country: "United States",
    city: "Sunnyvale",
    founded: 1984,
    employees: "1001–5000",
    activeCases: 2,
    totalVerifications: 33,
  },
  {
    id: "org-20",
    name: "Hooli Inc",
    state: "verified",
    orgType: "public_company",
    country: "United States",
    city: "Palo Alto",
    founded: 2003,
    employees: "5001+",
    activeCases: 1,
    totalVerifications: 96,
  },
  {
    id: "org-21",
    name: "Massive Dynamic",
    state: "verified",
    orgType: "private_company",
    country: "United States",
    city: "Boston",
    founded: 1994,
    employees: "1001–5000",
    activeCases: 2,
    totalVerifications: 27,
  },
  {
    id: "org-22",
    name: "Soylent Corp",
    state: "verified",
    orgType: "public_company",
    country: "United States",
    city: "Los Angeles",
    founded: 1973,
    employees: "5001+",
    activeCases: 1,
    totalVerifications: 41,
  },
  {
    id: "org-23",
    name: "Pied Piper",
    state: "verified",
    orgType: "private_company",
    country: "United States",
    city: "San Francisco",
    founded: 2014,
    employees: "11–50",
    activeCases: 2,
    totalVerifications: 18,
  },
  {
    id: "org-24",
    name: "Vandelay Industries",
    state: "duplicate_review",
    orgType: "private_company",
    country: "United States",
    city: "New York",
    founded: 1998,
    employees: "201–500",
    activeCases: 1,
    totalVerifications: 22,
    possibleDuplicates: ["org-24b"],
    registryFlags: ["possible_duplicate"],
  },
  {
    id: "org-24b",
    name: "Vandelay Imports Inc",
    state: "unverified",
    orgType: "private_company",
    country: "United States",
    city: "New York",
    founded: 1999,
    employees: "51–200",
    contacts: 0,
    activeCases: 0,
    totalVerifications: 0,
    possibleDuplicates: ["org-24"],
    registryFlags: ["possible_duplicate"],
  },
  {
    id: "org-25",
    name: "Kairo Verified ID",
    state: "verified",
    orgType: "platform",
    country: "Netherlands",
    city: "Amsterdam",
    founded: 2023,
    employees: "51–200",
    activeCases: 0,
    totalVerifications: 320,
  },
  {
    id: "org-26",
    name: "GitHub Contributions",
    state: "verified",
    orgType: "platform",
    country: "United States",
    city: "San Francisco",
    founded: 2008,
    employees: "5001+",
    activeCases: 0,
    totalVerifications: 61,
  },
  {
    id: "org-27",
    name: "Weyland-Yutani",
    state: "verified",
    orgType: "private_company",
    country: "Japan",
    city: "Tokyo",
    founded: 2099,
    employees: "5001+",
    activeCases: 1,
    totalVerifications: 14,
  },
  {
    id: "org-28",
    name: "Tyrell Corporation",
    state: "verified",
    orgType: "private_company",
    country: "United States",
    city: "Los Angeles",
    founded: 2019,
    employees: "1001–5000",
    activeCases: 1,
    totalVerifications: 9,
  },
  {
    id: "org-29",
    name: "Aperture Science",
    state: "verified",
    orgType: "private_company",
    country: "United States",
    city: "Cleveland",
    founded: 1953,
    employees: "1001–5000",
    activeCases: 0,
    totalVerifications: 24,
  },
  {
    id: "org-30",
    name: "Oscorp Industries",
    state: "deprecated",
    orgType: "public_company",
    country: "United States",
    city: "New York",
    founded: 1961,
    employees: "5001+",
    activeCases: 0,
    totalVerifications: 3,
    registryFlags: ["risk_review_required"],
  },
  {
    id: "org-31",
    name: "InGen Corporation",
    state: "verified",
    orgType: "private_company",
    country: "Costa Rica",
    city: "San José",
    founded: 1985,
    employees: "201–500",
    activeCases: 0,
    totalVerifications: 6,
  },
  {
    id: "org-32",
    name: "Nakatomi Trading",
    state: "verified",
    orgType: "private_company",
    country: "Japan",
    city: "Tokyo",
    founded: 1972,
    employees: "5001+",
    activeCases: 0,
    totalVerifications: 12,
  },
  {
    id: "org-33",
    name: "LexCorp",
    state: "verified",
    orgType: "public_company",
    country: "United States",
    city: "Metropolis",
    founded: 1970,
    employees: "5001+",
    activeCases: 0,
    totalVerifications: 17,
  },
  {
    id: "org-34",
    name: "Blue Sun",
    state: "verified",
    orgType: "private_company",
    country: "United States",
    city: "San Francisco",
    founded: 2001,
    employees: "1001–5000",
    activeCases: 0,
    totalVerifications: 5,
  },
];

const CONTACT_TEMPLATES: Array<Omit<RegistryContact, "id" | "addedAt" | "lastSuccessfulUse">> = [
  {
    name: "Sabine Keller",
    role: "hr",
    jobTitle: "HR Manager",
    emailMasked: "",
    state: "approved",
    confidence: 0.9,
    bounceCount: 0,
    addedBy: "System (previous verification)",
  },
  {
    name: "People Operations",
    role: "shared_inbox",
    jobTitle: "Shared inbox",
    emailMasked: "",
    state: "needs_review",
    confidence: 0.62,
    bounceCount: 0,
    addedBy: "Domain discovery",
  },
  {
    name: "Alex Nordgren",
    role: "manager",
    jobTitle: "Engineering Manager",
    emailMasked: "",
    state: "unverified",
    confidence: 0.55,
    bounceCount: 0,
    addedBy: "Candidate provided",
  },
];

function buildContacts(seed: OrgSeed): RegistryContact[] {
  if (seed.contacts === 0) return [];
  const count = seed.contacts ?? Math.min(3, 1 + (Number(seed.id.replace(/\D/g, "")) % 3));
  const domain = `${slug(seed.name)}.example`;
  const list: RegistryContact[] = [];
  for (let i = 0; i < count; i++) {
    const tpl = CONTACT_TEMPLATES[i % CONTACT_TEMPLATES.length];
    const local = tpl.name.toLowerCase().split(" ")[0];
    const state: RegistryContactState =
      seed.registryFlags?.includes("email_bounced") && i === 0 ? "bounced" : tpl.state;
    list.push({
      ...tpl,
      id: `${seed.id}-c${i + 1}`,
      emailMasked: mask(local, domain),
      state,
      bounceCount: state === "bounced" ? 1 : 0,
      addedAt: ago(120 - i * 30),
      lastSuccessfulUse: state === "approved" ? ago(30 + i * 10) : undefined,
    });
  }
  return list;
}

function buildActivity(seed: OrgSeed): RegistryActivityEvent[] {
  const events: RegistryActivityEvent[] = [
    {
      id: `${seed.id}-a1`,
      at: ago(400),
      kind: "created",
      actor: "System",
      description: "Organization created in registry.",
    },
  ];
  if (seed.totalVerifications > 5) {
    events.push({
      id: `${seed.id}-a2`,
      at: ago(60),
      kind: "outreach_sent",
      actor: "Aman Jha",
      description: "Outreach sent for KVR verification.",
    });
    events.push({
      id: `${seed.id}-a3`,
      at: ago(58),
      kind: "outreach_response",
      actor: "Verifier",
      description: "Employer confirmed a candidate claim.",
    });
  }
  if (seed.registryFlags?.includes("possible_duplicate")) {
    events.push({
      id: `${seed.id}-a4`,
      at: ago(14),
      kind: "duplicate_flagged",
      actor: "System",
      description: "Flagged as possible duplicate of another registry record.",
    });
  }
  if (seed.registryFlags?.includes("email_bounced")) {
    events.push({
      id: `${seed.id}-a5`,
      at: ago(7),
      kind: "contact_bounced",
      actor: "System",
      description: "Primary HR contact bounced during outreach.",
    });
  }
  return events;
}

function toOrg(seed: OrgSeed): RegistryOrganization {
  const domain = `${slug(seed.name)}.example`;
  const contacts = buildContacts(seed);
  return {
    id: seed.id,
    canonicalName: seed.name,
    aliases: seed.aliases ?? [],
    state: seed.state,
    orgType: seed.orgType,
    domain,
    website: `https://${domain}`,
    country: seed.country,
    headquartersCity: seed.city,
    yearFounded: seed.founded,
    employeesRange: seed.employees,
    description:
      seed.description ??
      `${seed.name} is a ${REGISTRY_ORG_TYPE_LABEL[seed.orgType].toLowerCase()} used by Kairo for verification lookups.`,
    createdAt: ago(400),
    updatedAt: ago(Math.max(1, 30 - (Number(seed.id.replace(/\D/g, "")) % 30))),
    createdBy: "System",
    contacts,
    activity: buildActivity(seed),
    activeCaseCount: seed.activeCases,
    totalVerifications: seed.totalVerifications,
    duplicateOfId: seed.duplicateOf,
    possibleDuplicateIds: seed.possibleDuplicates ?? [],
    registryFlags: seed.registryFlags ?? [],
  };
}

export const mockRegistryOrganizations: RegistryOrganization[] = SEEDS.map(toOrg);

export function getRegistryOrganization(id: string): RegistryOrganization | undefined {
  return mockRegistryOrganizations.find((o) => o.id === id);
}

export function getRegistryContact(orgId: string, contactId: string): RegistryContact | undefined {
  const org = getRegistryOrganization(orgId);
  return org?.contacts.find((c) => c.id === contactId);
}

/** Rollup used by the registry list header. */
export function getRegistryMetrics() {
  const orgs = mockRegistryOrganizations;
  const verified = orgs.filter((o) => o.state === "verified").length;
  const unverified = orgs.filter((o) => o.state === "unverified").length;
  const duplicates = orgs.filter((o) => o.state === "duplicate_review").length;
  const deprecated = orgs.filter((o) => o.state === "deprecated").length;
  const contactsTotal = orgs.reduce((n, o) => n + o.contacts.length, 0);
  const contactsApproved = orgs.reduce(
    (n, o) => n + o.contacts.filter((c) => c.state === "approved").length,
    0,
  );
  const contactsBounced = orgs.reduce(
    (n, o) => n + o.contacts.filter((c) => c.state === "bounced").length,
    0,
  );
  const activeCases = orgs.reduce((n, o) => n + o.activeCaseCount, 0);
  return {
    total: orgs.length,
    verified,
    unverified,
    duplicates,
    deprecated,
    contactsTotal,
    contactsApproved,
    contactsBounced,
    activeCases,
  };
}
