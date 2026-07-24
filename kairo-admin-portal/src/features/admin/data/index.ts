// Admin data adapter facade. Import from here (not from `mock-data/*`) so
// backend integration is a single-file swap per domain. See ./README.md.

export * as verifications from "./verifications";
export * as cases from "./cases";
export * as users from "./users";
export * as registry from "./registry";
export * as communications from "./communications";
export * as risk from "./risk";
export * as system from "./system";
export * as overview from "./overview";
export * from "./types";
