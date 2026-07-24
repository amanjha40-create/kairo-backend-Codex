import { describe, expect, it } from "vitest";
import { mapHttpStatusToApiError } from "./errors";

describe("mapHttpStatusToApiError", () => {
  it("maps 401 responses to unauthorized errors", () => {
    const error = mapHttpStatusToApiError(401, "req-1");
    expect(error.code).toBe("unauthorized");
    expect(error.requestId).toBe("req-1");
  });

  it("maps 422 responses to validation errors", () => {
    const error = mapHttpStatusToApiError(422, null, { field: "email" });
    expect(error.code).toBe("validation");
  });

  it("maps 500 responses to server errors", () => {
    const error = mapHttpStatusToApiError(500, null);
    expect(error.code).toBe("server");
  });
});
