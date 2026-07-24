/**
 * Admin — Users mock data.
 *
 * Deterministic seed. IDs are stable; timestamps are derived from a single
 * frozen NOW so re-renders don't shift the data. Candidate IDs match the
 * `candidateId` values in verification-cases.ts so the User Detail workspace
 * can cross-link to real mock cases (`/admin/verifications/$caseId`).
 */
import { mockVerificationCases } from "./verification-cases";

export type UserAccountStatus =
  "active" | "pending" | "disabled" | "suspended" | "deletion_requested";

export type OnboardingStep =
  | "welcome"
  | "create_account"
  | "verify_identity"
  | "choose_start_method"
  | "resume_or_quick"
  | "passport_created"
  | "home";

export type OnboardingState = "in_progress" | "completed" | "blocked" | "abandoned";
export type ProfileType = "candidate" | "student" | "professional" | "freelancer" | "gig_worker";
export type PassportStatus = "not_created" | "draft" | "active" | "revoked" | "suspended";
export type TrustBand = "low" | "developing" | "established" | "high" | "trusted";
export type StartMethod = "resume_import" | "quick_profile" | "manual";

export type UserAttentionKind =
  | "risk"
  | "onboarding_blocked"
  | "failed_outreach"
  | "documents_missing"
  | "email_bounce"
  | "identity_review";

export type SecurityEventKind =
  | "login_success"
  | "login_failed"
  | "password_reset_requested"
  | "email_change"
  | "phone_change"
  | "account_status_change"
  | "session_revoked"
  | "suspicious";

export type UserActivityKind =
  | "registration"
  | "email_verified"
  | "phone_verified"
  | "onboarding_step"
  | "profile_update"
  | "document_added"
  | "verification_requested"
  | "verification_decided"
  | "passport_share_created"
  | "passport_view"
  | "password_reset"
  | "account_change"
  | "admin_note"
  | "risk_flag";

export const ACCOUNT_STATUS_LABEL: Record<UserAccountStatus, string> = {
  active: "Active",
  pending: "Pending",
  disabled: "Disabled",
  suspended: "Suspended",
  deletion_requested: "Deletion requested",
};

export const ONBOARDING_STEP_LABEL: Record<OnboardingStep, string> = {
  welcome: "Welcome",
  create_account: "Create account",
  verify_identity: "Verify identity",
  choose_start_method: "Choose start method",
  resume_or_quick: "Resume import or Quick profile",
  passport_created: "Passport created",
  home: "Home",
};

export const ONBOARDING_STEP_ORDER: OnboardingStep[] = [
  "welcome",
  "create_account",
  "verify_identity",
  "choose_start_method",
  "resume_or_quick",
  "passport_created",
  "home",
];

export const PROFILE_TYPE_LABEL: Record<ProfileType, string> = {
  candidate: "Candidate",
  student: "Student",
  professional: "Professional",
  freelancer: "Freelancer",
  gig_worker: "Gig worker",
};

export const PASSPORT_STATUS_LABEL: Record<PassportStatus, string> = {
  not_created: "Not created",
  draft: "Draft",
  active: "Active",
  revoked: "Revoked",
  suspended: "Suspended",
};

export const TRUST_BAND_LABEL: Record<TrustBand, string> = {
  low: "Low",
  developing: "Developing",
  established: "Established",
  high: "High",
  trusted: "Trusted",
};

export const ATTENTION_LABEL: Record<UserAttentionKind, string> = {
  risk: "Risk review",
  onboarding_blocked: "Onboarding blocked",
  failed_outreach: "Failed outreach",
  documents_missing: "Documents missing",
  email_bounce: "Email bounce",
  identity_review: "Identity review",
};

export interface CareerRecord {
  id: string;
  kind:
    "employment" | "education" | "internship" | "freelance" | "gig" | "certification" | "project";
  title: string;
  organization: string;
  period: string;
  claimStatus: "unverified" | "in_progress" | "verified" | "disputed";
  verificationStatus: "not_started" | "pending" | "verified" | "rejected" | "unable";
  evidenceCount: number;
  lastUpdatedAt: string;
  relatedCaseId?: string;
}

export interface DocumentSummary {
  id: string;
  type: string;
  relatedClaim: string;
  reviewStatus: "not_reviewed" | "in_review" | "accepted" | "rejected";
  extractionStatus: "pending" | "complete" | "failed";
  verificationStatus: "not_started" | "pending" | "verified" | "rejected";
  uploadedAt: string;
  expiresAt?: string;
  relatedCaseId?: string;
}

export interface ShareRecord {
  id: string;
  label: string;
  scope: "full_passport" | "employment_only" | "education_only" | "custom";
  status: "active" | "revoked" | "expired";
  createdAt: string;
  expiresAt?: string;
  viewCount: number;
  lastViewedAt?: string;
}

export interface SecurityEvent {
  id: string;
  at: string;
  kind: SecurityEventKind;
  outcome: "success" | "failed" | "info";
  deviceCategory: string;
  approximateLocation: string;
  summary: string;
}

export interface UserActivityEvent {
  id: string;
  at: string;
  kind: UserActivityKind;
  summary: string;
  sessionOnly?: boolean;
  actor?: string;
}

export interface TrustScoreSummary {
  current: number;
  band: TrustBand;
  verifiedSignals: number;
  pendingSignals: number;
  expiredSignals: number;
  riskDeductions: number;
  lastRecalculatedAt: string;
  contributingFactors: string[];
}

export interface OnboardingSummary {
  state: OnboardingState;
  currentStep: OnboardingStep;
  completedSteps: OnboardingStep[];
  blockedStep?: OnboardingStep;
  blockedReason?: string;
  lastActivityAt: string;
  startMethod?: StartMethod;
  resumeImport?: {
    filename: string;
    parsedFields: number;
    warnings: number;
  };
  profileCompletionPct: number;
}

export interface PassportOverview {
  status: PassportStatus;
  passportId?: string;
  lastUpdatedAt: string;
  publicShareEnabled: boolean;
  sections: {
    identity: number;
    employment: number;
    education: number;
    certifications: number;
    internships: number;
    freelance: number;
    projects: number;
    documents: number;
  };
}

export interface UserRecord {
  id: string; // matches candidateId in verification-cases
  displayId: string; // "USR-24001"
  fullName: string;
  email: string;
  phone: string;
  profileType: ProfileType;
  location: string;
  joinedAt: string;
  lastActiveAt: string;
  accountStatus: UserAccountStatus;
  emailVerified: boolean;
  phoneVerified: boolean;
  identityVerified: boolean;
  employer?: string;
  educationInstitution?: string;
  onboarding: OnboardingSummary;
  passport: PassportOverview;
  trustScore: TrustScoreSummary;
  attentionFlags: UserAttentionKind[];
  careerRecords: CareerRecord[];
  documents: DocumentSummary[];
  shares: ShareRecord[];
  security: SecurityEvent[];
  activity: UserActivityEvent[];
}

// ---------- Deterministic time helpers ----------
const NOW = new Date(Math.floor(Date.now() / 3_600_000) * 3_600_000);
function iso(days: number, hours = 0): string {
  const d = new Date(NOW);
  d.setUTCHours(d.getUTCHours() - hours);
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString();
}

// ---------- Base directory (12 seeded, ~14 more terse rows for scale) ----------
interface Seed {
  id: string;
  fullName: string;
  email: string;
  phone: string;
  profileType: ProfileType;
  location: string;
  joinedDaysAgo: number;
  lastActiveHoursAgo: number;
  accountStatus: UserAccountStatus;
  emailVerified: boolean;
  phoneVerified: boolean;
  identityVerified: boolean;
  employer?: string;
  educationInstitution?: string;
  onboardingState: OnboardingState;
  currentStep: OnboardingStep;
  blockedStep?: OnboardingStep;
  blockedReason?: string;
  startMethod?: StartMethod;
  completionPct: number;
  passportStatus: PassportStatus;
  publicShare: boolean;
  score: number;
  band: TrustBand;
  verified: number;
  pending: number;
  expired: number;
  deductions: number;
  factors: string[];
  attention: UserAttentionKind[];
}

const SEEDS: Seed[] = [
  {
    id: "cand-101",
    fullName: "Jonas Weiss",
    email: "jonas.weiss@example.com",
    phone: "+49 30 5550 1010",
    profileType: "professional",
    location: "Berlin, DE",
    joinedDaysAgo: 220,
    lastActiveHoursAgo: 3,
    accountStatus: "active",
    emailVerified: true,
    phoneVerified: true,
    identityVerified: true,
    employer: "Siemens AG",
    educationInstitution: "TU Berlin",
    onboardingState: "completed",
    currentStep: "home",
    startMethod: "resume_import",
    completionPct: 92,
    passportStatus: "active",
    publicShare: true,
    score: 78,
    band: "high",
    verified: 7,
    pending: 2,
    expired: 0,
    deductions: 0,
    factors: ["Verified employer via HR contact", "Identity confirmed", "3 recent projects"],
    attention: [],
  },
  {
    id: "cand-102",
    fullName: "Priya Shah",
    email: "priya.shah@example.com",
    phone: "+91 22 5550 2211",
    profileType: "professional",
    location: "Mumbai, IN",
    joinedDaysAgo: 180,
    lastActiveHoursAgo: 26,
    accountStatus: "active",
    emailVerified: true,
    phoneVerified: true,
    identityVerified: true,
    employer: "Infosys",
    educationInstitution: "IIT Bombay",
    onboardingState: "completed",
    currentStep: "home",
    startMethod: "resume_import",
    completionPct: 88,
    passportStatus: "active",
    publicShare: false,
    score: 72,
    band: "high",
    verified: 6,
    pending: 1,
    expired: 1,
    deductions: 0,
    factors: ["Employer verified", "Education institution confirmed"],
    attention: [],
  },
  {
    id: "cand-103",
    fullName: "Marco Bianchi",
    email: "marco.bianchi@example.com",
    phone: "+39 06 5550 4402",
    profileType: "freelancer",
    location: "Rome, IT",
    joinedDaysAgo: 95,
    lastActiveHoursAgo: 8,
    accountStatus: "active",
    emailVerified: true,
    phoneVerified: true,
    identityVerified: false,
    employer: "Independent",
    onboardingState: "in_progress",
    currentStep: "verify_identity",
    completionPct: 55,
    passportStatus: "draft",
    publicShare: false,
    score: 41,
    band: "developing",
    verified: 2,
    pending: 3,
    expired: 0,
    deductions: 4,
    factors: ["Identity check pending", "Recent document mismatch flag"],
    attention: ["identity_review", "documents_missing"],
  },
  {
    id: "cand-104",
    fullName: "Lena Fischer",
    email: "lena.fischer@example.com",
    phone: "+43 1 5550 3013",
    profileType: "student",
    location: "Vienna, AT",
    joinedDaysAgo: 45,
    lastActiveHoursAgo: 72,
    accountStatus: "pending",
    emailVerified: true,
    phoneVerified: false,
    identityVerified: false,
    educationInstitution: "University of Vienna",
    onboardingState: "blocked",
    currentStep: "verify_identity",
    blockedStep: "verify_identity",
    blockedReason: "Selfie liveness check failed twice",
    startMethod: "quick_profile",
    completionPct: 32,
    passportStatus: "draft",
    publicShare: false,
    score: 24,
    band: "low",
    verified: 1,
    pending: 2,
    expired: 0,
    deductions: 0,
    factors: ["Onboarding blocked at identity"],
    attention: ["onboarding_blocked", "identity_review"],
  },
  {
    id: "cand-105",
    fullName: "Ravi Patel",
    email: "ravi.patel@example.com",
    phone: "+91 80 5550 8811",
    profileType: "professional",
    location: "Bengaluru, IN",
    joinedDaysAgo: 310,
    lastActiveHoursAgo: 1,
    accountStatus: "active",
    emailVerified: true,
    phoneVerified: true,
    identityVerified: true,
    employer: "Flipkart",
    educationInstitution: "NIT Warangal",
    onboardingState: "completed",
    currentStep: "home",
    startMethod: "resume_import",
    completionPct: 95,
    passportStatus: "active",
    publicShare: true,
    score: 84,
    band: "trusted",
    verified: 9,
    pending: 0,
    expired: 0,
    deductions: 0,
    factors: ["All employment verified", "3 verified certifications"],
    attention: [],
  },
  {
    id: "cand-106",
    fullName: "Sofia Martins",
    email: "sofia.martins@example.com",
    phone: "+351 21 5550 6666",
    profileType: "professional",
    location: "Lisbon, PT",
    joinedDaysAgo: 120,
    lastActiveHoursAgo: 14,
    accountStatus: "active",
    emailVerified: true,
    phoneVerified: true,
    identityVerified: true,
    employer: "Farfetch",
    onboardingState: "completed",
    currentStep: "home",
    startMethod: "resume_import",
    completionPct: 90,
    passportStatus: "active",
    publicShare: true,
    score: 69,
    band: "high",
    verified: 5,
    pending: 1,
    expired: 1,
    deductions: 0,
    factors: ["Employer verified", "One expired certification"],
    attention: [],
  },
  {
    id: "cand-107",
    fullName: "Daniel Kim",
    email: "daniel.kim@example.com",
    phone: "+82 2 5550 7788",
    profileType: "professional",
    location: "Seoul, KR",
    joinedDaysAgo: 60,
    lastActiveHoursAgo: 200,
    accountStatus: "disabled",
    emailVerified: true,
    phoneVerified: true,
    identityVerified: false,
    employer: "Kakao",
    onboardingState: "abandoned",
    currentStep: "choose_start_method",
    completionPct: 20,
    passportStatus: "revoked",
    publicShare: false,
    score: 12,
    band: "low",
    verified: 0,
    pending: 0,
    expired: 2,
    deductions: 8,
    factors: ["Account disabled by Trust & Safety", "Multiple failed logins"],
    attention: ["risk"],
  },
  {
    id: "cand-108",
    fullName: "Ines Duarte",
    email: "ines.duarte@example.com",
    phone: "+55 11 5550 9988",
    profileType: "student",
    location: "São Paulo, BR",
    joinedDaysAgo: 10,
    lastActiveHoursAgo: 4,
    accountStatus: "active",
    emailVerified: false,
    phoneVerified: false,
    identityVerified: false,
    educationInstitution: "USP",
    onboardingState: "in_progress",
    currentStep: "create_account",
    startMethod: "quick_profile",
    completionPct: 12,
    passportStatus: "not_created",
    publicShare: false,
    score: 0,
    band: "low",
    verified: 0,
    pending: 0,
    expired: 0,
    deductions: 0,
    factors: ["Account just created", "Email verification pending"],
    attention: ["email_bounce"],
  },
  {
    id: "cand-109",
    fullName: "Hiroshi Tanaka",
    email: "hiroshi.tanaka@example.com",
    phone: "+81 3 5550 4400",
    profileType: "professional",
    location: "Tokyo, JP",
    joinedDaysAgo: 400,
    lastActiveHoursAgo: 48,
    accountStatus: "active",
    emailVerified: true,
    phoneVerified: true,
    identityVerified: true,
    employer: "Rakuten",
    onboardingState: "completed",
    currentStep: "home",
    startMethod: "resume_import",
    completionPct: 93,
    passportStatus: "active",
    publicShare: false,
    score: 76,
    band: "high",
    verified: 6,
    pending: 0,
    expired: 2,
    deductions: 0,
    factors: ["Long-tenured account", "Certifications refresh needed"],
    attention: [],
  },
  {
    id: "cand-110",
    fullName: "Emily Carter",
    email: "emily.carter@example.com",
    phone: "+1 415 555 0110",
    profileType: "gig_worker",
    location: "San Francisco, US",
    joinedDaysAgo: 75,
    lastActiveHoursAgo: 6,
    accountStatus: "suspended",
    emailVerified: true,
    phoneVerified: true,
    identityVerified: true,
    employer: "Uber, DoorDash",
    onboardingState: "completed",
    currentStep: "home",
    startMethod: "manual",
    completionPct: 70,
    passportStatus: "suspended",
    publicShare: false,
    score: 30,
    band: "developing",
    verified: 3,
    pending: 2,
    expired: 1,
    deductions: 6,
    factors: ["Suspended pending Trust & Safety review"],
    attention: ["risk", "failed_outreach"],
  },
  {
    id: "cand-111",
    fullName: "Aisha Bello",
    email: "aisha.bello@example.com",
    phone: "+234 1 5550 3300",
    profileType: "professional",
    location: "Lagos, NG",
    joinedDaysAgo: 150,
    lastActiveHoursAgo: 32,
    accountStatus: "active",
    emailVerified: true,
    phoneVerified: true,
    identityVerified: true,
    employer: "Andela",
    onboardingState: "completed",
    currentStep: "home",
    startMethod: "resume_import",
    completionPct: 87,
    passportStatus: "active",
    publicShare: true,
    score: 71,
    band: "high",
    verified: 5,
    pending: 2,
    expired: 0,
    deductions: 0,
    factors: ["Employer verified", "2 pending certifications"],
    attention: [],
  },
  {
    id: "cand-112",
    fullName: "Noah Bergström",
    email: "noah.b@example.com",
    phone: "+46 8 5550 7712",
    profileType: "freelancer",
    location: "Stockholm, SE",
    joinedDaysAgo: 200,
    lastActiveHoursAgo: 96,
    accountStatus: "deletion_requested",
    emailVerified: true,
    phoneVerified: true,
    identityVerified: true,
    employer: "Independent",
    onboardingState: "completed",
    currentStep: "home",
    startMethod: "resume_import",
    completionPct: 80,
    passportStatus: "revoked",
    publicShare: false,
    score: 55,
    band: "established",
    verified: 4,
    pending: 0,
    expired: 0,
    deductions: 0,
    factors: ["Deletion request pending review"],
    attention: [],
  },
];

// A handful of thinner rows for directory scale (no career/documents needed).
const EXTRA_NAMES: Array<{
  id: string;
  name: string;
  email: string;
  type: ProfileType;
  loc: string;
  status: UserAccountStatus;
  band: TrustBand;
  score: number;
  verified: number;
  pending: number;
  last: number;
  onb: OnboardingState;
  step: OnboardingStep;
  attention: UserAttentionKind[];
  passport: PassportStatus;
}> = [
  {
    id: "cand-113",
    name: "Yara Haddad",
    email: "yara.haddad@example.com",
    type: "professional",
    loc: "Beirut, LB",
    status: "active",
    band: "high",
    score: 74,
    verified: 5,
    pending: 1,
    last: 12,
    onb: "completed",
    step: "home",
    attention: [],
    passport: "active",
  },
  {
    id: "cand-114",
    name: "Kwame Mensah",
    email: "kwame.mensah@example.com",
    type: "student",
    loc: "Accra, GH",
    status: "active",
    band: "developing",
    score: 44,
    verified: 2,
    pending: 2,
    last: 18,
    onb: "in_progress",
    step: "resume_or_quick",
    attention: [],
    passport: "draft",
  },
  {
    id: "cand-115",
    name: "Chen Wei",
    email: "chen.wei@example.com",
    type: "professional",
    loc: "Shanghai, CN",
    status: "active",
    band: "trusted",
    score: 82,
    verified: 8,
    pending: 0,
    last: 2,
    onb: "completed",
    step: "home",
    attention: [],
    passport: "active",
  },
  {
    id: "cand-116",
    name: "Owen Reilly",
    email: "owen.reilly@example.com",
    type: "freelancer",
    loc: "Dublin, IE",
    status: "pending",
    band: "low",
    score: 18,
    verified: 0,
    pending: 2,
    last: 100,
    onb: "blocked",
    step: "verify_identity",
    attention: ["onboarding_blocked"],
    passport: "not_created",
  },
  {
    id: "cand-117",
    name: "Fatima Zahra",
    email: "fatima.zahra@example.com",
    type: "professional",
    loc: "Casablanca, MA",
    status: "active",
    band: "high",
    score: 70,
    verified: 5,
    pending: 1,
    last: 10,
    onb: "completed",
    step: "home",
    attention: [],
    passport: "active",
  },
  {
    id: "cand-118",
    name: "Andrés Rojas",
    email: "andres.rojas@example.com",
    type: "professional",
    loc: "Bogotá, CO",
    status: "active",
    band: "established",
    score: 58,
    verified: 4,
    pending: 2,
    last: 20,
    onb: "completed",
    step: "home",
    attention: ["failed_outreach"],
    passport: "active",
  },
  {
    id: "cand-119",
    name: "Mira Novak",
    email: "mira.novak@example.com",
    type: "student",
    loc: "Prague, CZ",
    status: "active",
    band: "developing",
    score: 39,
    verified: 2,
    pending: 1,
    last: 30,
    onb: "in_progress",
    step: "choose_start_method",
    attention: [],
    passport: "draft",
  },
  {
    id: "cand-120",
    name: "Julia Kowalski",
    email: "julia.kowalski@example.com",
    type: "professional",
    loc: "Warsaw, PL",
    status: "active",
    band: "high",
    score: 73,
    verified: 6,
    pending: 0,
    last: 5,
    onb: "completed",
    step: "home",
    attention: [],
    passport: "active",
  },
  {
    id: "cand-121",
    name: "Tomás Silva",
    email: "tomas.silva@example.com",
    type: "professional",
    loc: "Porto, PT",
    status: "disabled",
    band: "low",
    score: 10,
    verified: 1,
    pending: 0,
    last: 500,
    onb: "abandoned",
    step: "welcome",
    attention: ["risk"],
    passport: "revoked",
  },
  {
    id: "cand-122",
    name: "Elif Demir",
    email: "elif.demir@example.com",
    type: "professional",
    loc: "Istanbul, TR",
    status: "active",
    band: "high",
    score: 68,
    verified: 5,
    pending: 1,
    last: 8,
    onb: "completed",
    step: "home",
    attention: [],
    passport: "active",
  },
  {
    id: "cand-123",
    name: "Bruno Costa",
    email: "bruno.costa@example.com",
    type: "gig_worker",
    loc: "Rio, BR",
    status: "active",
    band: "developing",
    score: 36,
    verified: 2,
    pending: 2,
    last: 40,
    onb: "in_progress",
    step: "resume_or_quick",
    attention: ["documents_missing"],
    passport: "draft",
  },
  {
    id: "cand-124",
    name: "Nadia Popov",
    email: "nadia.popov@example.com",
    type: "professional",
    loc: "Sofia, BG",
    status: "active",
    band: "established",
    score: 61,
    verified: 4,
    pending: 1,
    last: 15,
    onb: "completed",
    step: "home",
    attention: [],
    passport: "active",
  },
];

// ---------- Builders ----------
function stepCompletion(current: OnboardingStep, state: OnboardingState): OnboardingStep[] {
  const idx = ONBOARDING_STEP_ORDER.indexOf(current);
  if (state === "completed") return ONBOARDING_STEP_ORDER.slice();
  return ONBOARDING_STEP_ORDER.slice(0, Math.max(0, idx));
}

function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function displayIdOf(id: string): string {
  const n = Number(id.split("-")[1] ?? "0");
  return `USR-${(24000 + n).toString()}`;
}

function passportIdOf(id: string, status: PassportStatus): string | undefined {
  if (status === "not_created") return undefined;
  const n = Number(id.split("-")[1] ?? "0");
  return `PPT-${(90000 + n * 7).toString()}`;
}

function buildRecordFromSeed(s: Seed): UserRecord {
  const casesForUser = mockVerificationCases.filter((c) => c.candidateId === s.id);
  const careerRecords: CareerRecord[] = casesForUser.map((c, i) => ({
    id: `car-${s.id}-${i}`,
    kind:
      c.verificationType === "employment"
        ? "employment"
        : c.verificationType === "education"
          ? "education"
          : c.verificationType === "certification"
            ? "certification"
            : "employment",
    title: c.roleOrProgram,
    organization: c.organizationName,
    period: "—",
    claimStatus:
      c.status === "verified" ? "verified" : c.status === "rejected" ? "disputed" : "in_progress",
    verificationStatus:
      c.status === "verified"
        ? "verified"
        : c.status === "rejected"
          ? "rejected"
          : c.status === "unable_to_verify"
            ? "unable"
            : "pending",
    evidenceCount: c.evidenceCount,
    lastUpdatedAt: c.updatedAt,
    relatedCaseId: c.id,
  }));

  const documents: DocumentSummary[] = casesForUser.slice(0, 4).map((c, i) => ({
    id: `doc-${s.id}-${i}`,
    type:
      c.verificationType === "employment"
        ? "Offer letter"
        : c.verificationType === "education"
          ? "Degree certificate"
          : c.verificationType === "certification"
            ? "Certification PDF"
            : "Government ID",
    relatedClaim: `${c.organizationName} — ${c.roleOrProgram}`,
    reviewStatus:
      c.status === "verified" ? "accepted" : c.status === "rejected" ? "rejected" : "in_review",
    extractionStatus: "complete",
    verificationStatus:
      c.status === "verified" ? "verified" : c.status === "rejected" ? "rejected" : "pending",
    uploadedAt: c.submittedAt,
    expiresAt: c.verificationType === "certification" ? iso(-365) : undefined,
    relatedCaseId: c.id,
  }));

  const shares: ShareRecord[] =
    s.passportStatus === "active"
      ? [
          {
            id: `sh-${s.id}-1`,
            label: "Recruiter — Northwind",
            scope: "full_passport",
            status: "active",
            createdAt: iso(20),
            expiresAt: iso(-30),
            viewCount: 4,
            lastViewedAt: iso(2),
          },
          {
            id: `sh-${s.id}-2`,
            label: "Job application — Verdant",
            scope: "employment_only",
            status: "expired",
            createdAt: iso(90),
            expiresAt: iso(30),
            viewCount: 12,
            lastViewedAt: iso(35),
          },
        ]
      : [];

  const security: SecurityEvent[] = [
    {
      id: `sec-${s.id}-1`,
      at: iso(0, s.lastActiveHoursAgo),
      kind: "login_success",
      outcome: "success",
      deviceCategory: "Mobile — Android",
      approximateLocation: s.location,
      summary: "Successful sign-in",
    },
    {
      id: `sec-${s.id}-2`,
      at: iso(3),
      kind: "login_failed",
      outcome: "failed",
      deviceCategory: "Desktop — Chrome",
      approximateLocation: s.location,
      summary: "Wrong password (2 attempts)",
    },
    ...(s.accountStatus === "disabled" || s.accountStatus === "suspended"
      ? [
          {
            id: `sec-${s.id}-3`,
            at: iso(5),
            kind: "account_status_change" as SecurityEventKind,
            outcome: "info" as const,
            deviceCategory: "System",
            approximateLocation: "—",
            summary: `Account marked ${ACCOUNT_STATUS_LABEL[s.accountStatus]}`,
          },
        ]
      : []),
  ];

  const activity: UserActivityEvent[] = [
    {
      id: `act-${s.id}-1`,
      at: iso(s.joinedDaysAgo),
      kind: "registration",
      summary: "Account created",
    },
    ...(s.emailVerified
      ? [
          {
            id: `act-${s.id}-2`,
            at: iso(s.joinedDaysAgo - 1),
            kind: "email_verified" as UserActivityKind,
            summary: "Email verified",
          },
        ]
      : []),
    ...(s.phoneVerified
      ? [
          {
            id: `act-${s.id}-3`,
            at: iso(s.joinedDaysAgo - 1),
            kind: "phone_verified" as UserActivityKind,
            summary: "Phone verified",
          },
        ]
      : []),
    ...casesForUser.slice(0, 3).map((c, i) => ({
      id: `act-${s.id}-c${i}`,
      at: c.submittedAt,
      kind: "verification_requested" as UserActivityKind,
      summary: `Requested ${c.verificationType} verification — ${c.organizationName}`,
    })),
    ...casesForUser
      .filter((c) => c.status === "verified" || c.status === "rejected")
      .slice(0, 2)
      .map((c, i) => ({
        id: `act-${s.id}-d${i}`,
        at: c.updatedAt,
        kind: "verification_decided" as UserActivityKind,
        summary: `${c.status === "verified" ? "Verified" : "Rejected"} — ${c.organizationName}`,
      })),
  ];

  return {
    id: s.id,
    displayId: displayIdOf(s.id),
    fullName: s.fullName,
    email: s.email,
    phone: s.phone,
    profileType: s.profileType,
    location: s.location,
    joinedAt: iso(s.joinedDaysAgo),
    lastActiveAt: iso(0, s.lastActiveHoursAgo),
    accountStatus: s.accountStatus,
    emailVerified: s.emailVerified,
    phoneVerified: s.phoneVerified,
    identityVerified: s.identityVerified,
    employer: s.employer,
    educationInstitution: s.educationInstitution,
    onboarding: {
      state: s.onboardingState,
      currentStep: s.currentStep,
      completedSteps: stepCompletion(s.currentStep, s.onboardingState),
      blockedStep: s.blockedStep,
      blockedReason: s.blockedReason,
      lastActivityAt: iso(0, s.lastActiveHoursAgo),
      startMethod: s.startMethod,
      resumeImport:
        s.startMethod === "resume_import"
          ? {
              filename: `${s.fullName.split(" ")[0].toLowerCase()}_resume.pdf`,
              parsedFields: 22,
              warnings: 1,
            }
          : undefined,
      profileCompletionPct: s.completionPct,
    },
    passport: {
      status: s.passportStatus,
      passportId: passportIdOf(s.id, s.passportStatus),
      lastUpdatedAt: iso(2),
      publicShareEnabled: s.publicShare,
      sections: {
        identity: s.identityVerified ? 1 : 0,
        employment: careerRecords.filter((r) => r.kind === "employment").length,
        education: careerRecords.filter((r) => r.kind === "education").length,
        certifications: careerRecords.filter((r) => r.kind === "certification").length,
        internships: 0,
        freelance: 0,
        projects: 0,
        documents: documents.length,
      },
    },
    trustScore: {
      current: s.score,
      band: s.band,
      verifiedSignals: s.verified,
      pendingSignals: s.pending,
      expiredSignals: s.expired,
      riskDeductions: s.deductions,
      lastRecalculatedAt: iso(1),
      contributingFactors: s.factors,
    },
    attentionFlags: s.attention,
    careerRecords,
    documents,
    shares,
    security,
    activity,
  };
}

function buildThinRecord(x: (typeof EXTRA_NAMES)[number]): UserRecord {
  const seed: Seed = {
    id: x.id,
    fullName: x.name,
    email: x.email,
    phone: "+00 000 000 000",
    profileType: x.type,
    location: x.loc,
    joinedDaysAgo: 100,
    lastActiveHoursAgo: x.last,
    accountStatus: x.status,
    emailVerified: x.status !== "pending",
    phoneVerified: x.status === "active",
    identityVerified: x.passport === "active",
    onboardingState: x.onb,
    currentStep: x.step,
    completionPct: x.onb === "completed" ? 85 : 40,
    passportStatus: x.passport,
    publicShare: false,
    score: x.score,
    band: x.band,
    verified: x.verified,
    pending: x.pending,
    expired: 0,
    deductions: x.attention.includes("risk") ? 5 : 0,
    factors: ["Automated summary"],
    attention: x.attention,
    startMethod: x.onb === "completed" ? "resume_import" : "manual",
  };
  return buildRecordFromSeed(seed);
}

export const mockUsers: UserRecord[] = [
  ...SEEDS.map(buildRecordFromSeed),
  ...EXTRA_NAMES.map(buildThinRecord),
];

export function getUser(userId: string): UserRecord | undefined {
  return mockUsers.find((u) => u.id === userId || u.displayId === userId);
}

export function initialsFor(u: UserRecord): string {
  return initialsOf(u.fullName);
}

// ---------- Directory metrics ----------
export interface UserDirectoryMetrics {
  total: number;
  active: number;
  onboardingIncomplete: number;
  passportVerified: number;
  attentionRequired: number;
  disabled: number;
}

export function getUserDirectoryMetrics(): UserDirectoryMetrics {
  return {
    total: mockUsers.length,
    active: mockUsers.filter((u) => u.accountStatus === "active").length,
    onboardingIncomplete: mockUsers.filter((u) => u.onboarding.state !== "completed").length,
    passportVerified: mockUsers.filter((u) => u.passport.status === "active").length,
    attentionRequired: mockUsers.filter((u) => u.attentionFlags.length > 0).length,
    disabled: mockUsers.filter(
      (u) => u.accountStatus === "disabled" || u.accountStatus === "suspended",
    ).length,
  };
}
