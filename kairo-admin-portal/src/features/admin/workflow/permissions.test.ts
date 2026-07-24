import { describe, expect, it } from "vitest";
import { hasPermission, permissionsForRole } from "./permissions";

describe("permissionsForRole", () => {
  it("grants admin access to system controls", () => {
    const permissions = permissionsForRole("admin");
    expect(hasPermission(permissions, "system.alerts.manage")).toBe(true);
  });

  it("keeps read-only users out of privileged actions", () => {
    const permissions = permissionsForRole("read_only");
    expect(hasPermission(permissions, "system.alerts.manage")).toBe(false);
    expect(hasPermission(permissions, "users.view")).toBe(true);
  });
});
