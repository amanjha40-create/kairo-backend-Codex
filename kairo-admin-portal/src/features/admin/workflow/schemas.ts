/**
 * Zod validation schemas for every Kairo Admin verification workflow form.
 * Used inside dialogs; specific errors surface at the field level, never
 * only via disabled submit buttons.
 */
import { z } from "zod";
import { CORRECTION_REASONS, REJECTION_REASONS, UNABLE_REASONS, VERIFICATION_BASES } from "./types";

export const correctionSchema = z.object({
  reasons: z.array(z.enum(CORRECTION_REASONS)).min(1, "Select at least one correction reason."),
  affectedFieldKeys: z.array(z.string()).min(1, "Select at least one affected field."),
  requestedItems: z.array(z.string()).default([]),
  candidateMessage: z
    .string()
    .trim()
    .min(10, "Provide a candidate-facing correction message (at least 10 characters).")
    .max(2000, "Candidate message must be under 2000 characters."),
  internalNote: z.string().trim().max(2000).optional().or(z.literal("")),
});
export type CorrectionSchema = z.infer<typeof correctionSchema>;

export const outreachSchema = z.object({
  contactId: z.string().min(1, "Select an approved contact."),
  channel: z.literal("email"),
  internalNote: z.string().trim().max(2000).optional().or(z.literal("")),
});
export type OutreachSchema = z.infer<typeof outreachSchema>;

export const verifySchema = z.object({
  basis: z.enum(VERIFICATION_BASES, {
    errorMap: () => ({ message: "Choose the verification basis." }),
  }),
  fieldConfirmations: z
    .record(z.enum(["confirmed", "partially_confirmed", "not_confirmed", "not_applicable"]))
    .refine((v) => Object.values(v).some((s) => s === "confirmed" || s === "partially_confirmed"), {
      message: "At least one field must be confirmed or partially confirmed.",
    }),
  decisionSummary: z
    .string()
    .trim()
    .min(10, "Provide a decision summary (at least 10 characters)."),
  effectiveDate: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "Provide a valid effective date."),
  expiryDate: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/, "Provide a valid expiry date.")
    .optional()
    .or(z.literal("")),
  internalNote: z.string().trim().max(2000).optional().or(z.literal("")),
});
export type VerifySchema = z.infer<typeof verifySchema>;

export const rejectSchema = z.object({
  reason: z.enum(REJECTION_REASONS, {
    errorMap: () => ({ message: "Choose a rejection reason." }),
  }),
  decisionSummary: z
    .string()
    .trim()
    .min(20, "A rejection requires a substantiated case reason (at least 20 characters)."),
  supportingEvidenceIds: z
    .array(z.string())
    .min(1, "Choose the evidence or event supporting this decision."),
  candidateMessage: z.string().trim().min(10, "Provide a candidate-facing explanation."),
  internalNote: z.string().trim().max(2000).optional().or(z.literal("")),
  acknowledgement: z.literal(true, {
    errorMap: () => ({ message: "You must acknowledge the impact of rejection." }),
  }),
});
export type RejectSchema = z.infer<typeof rejectSchema>;

export const unableSchema = z.object({
  reason: z.enum(UNABLE_REASONS, {
    errorMap: () => ({ message: "Choose a reason." }),
  }),
  attemptsSummary: z.string().trim().min(10, "Summarize the attempts already made."),
  outstandingUncertainty: z.string().trim().min(10, "Describe the outstanding uncertainty."),
  candidateMessage: z.string().trim().min(10, "Provide a candidate-facing explanation."),
  internalNote: z.string().trim().max(2000).optional().or(z.literal("")),
});
export type UnableSchema = z.infer<typeof unableSchema>;

export const clarificationRequestSchema = z.object({
  question: z.string().trim().min(5, "Provide the clarification question."),
  affectedFieldKeys: z.array(z.string()).default([]),
  internalNote: z.string().trim().max(2000).optional().or(z.literal("")),
});
export type ClarificationRequestSchema = z.infer<typeof clarificationRequestSchema>;

export const clarificationResponseSchema = z.object({
  response: z.string().trim().min(5, "Provide the candidate response text."),
  updatedFieldKeys: z.array(z.string()).default([]),
  evidenceAdded: z.boolean().default(false),
  internalNote: z.string().trim().max(2000).optional().or(z.literal("")),
});
export type ClarificationResponseSchema = z.infer<typeof clarificationResponseSchema>;
