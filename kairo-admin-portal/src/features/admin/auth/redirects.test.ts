import { describe, expect, it } from "vitest";
import { isSafeAdminRedirect, normalizeAdminRedirect } from "./redirects";

describe("admin redirects", () => {
  it("accepts internal admin redirects", () => {
    expect(isSafeAdminRedirect("/admin/verifications")).toBe(true);
    expect(normalizeAdminRedirect("/admin/users")).toBe("/admin/users");
  });

  it("rejects open redirects", () => {
    expect(isSafeAdminRedirect("https://evil.example")).toBe(false);
    expect(isSafeAdminRedirect("//evil.example")).toBe(false);
    expect(isSafeAdminRedirect("/profile")).toBe(false);
    expect(normalizeAdminRedirect("https://evil.example")).toBe("/admin");
  });
});
