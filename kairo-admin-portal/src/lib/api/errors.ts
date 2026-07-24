export type ApiErrorCode =
  | "configuration"
  | "network"
  | "timeout"
  | "unauthorized"
  | "forbidden"
  | "not_found"
  | "conflict"
  | "validation"
  | "rate_limited"
  | "server"
  | "unknown";

export class ApiError extends Error {
  code: ApiErrorCode;
  status: number | null;
  requestId: string | null;
  details: unknown;

  constructor(options: {
    code: ApiErrorCode;
    message: string;
    status?: number | null;
    requestId?: string | null;
    details?: unknown;
  }) {
    super(options.message);
    this.name = "ApiError";
    this.code = options.code;
    this.status = options.status ?? null;
    this.requestId = options.requestId ?? null;
    this.details = options.details;
  }
}

export function getRequestId(headers: Headers): string | null {
  return (
    headers.get("x-request-id") ??
    headers.get("x-correlation-id") ??
    headers.get("traceparent") ??
    null
  );
}

export function mapHttpStatusToApiError(
  status: number,
  requestId: string | null,
  details?: unknown,
): ApiError {
  if (status === 401) {
    return new ApiError({
      code: "unauthorized",
      message: "Your session is no longer valid. Sign in again to continue.",
      status,
      requestId,
      details,
    });
  }

  if (status === 403) {
    return new ApiError({
      code: "forbidden",
      message: "You do not have permission to perform this action.",
      status,
      requestId,
      details,
    });
  }

  if (status === 404) {
    return new ApiError({
      code: "not_found",
      message: "The requested resource could not be found.",
      status,
      requestId,
      details,
    });
  }

  if (status === 409) {
    return new ApiError({
      code: "conflict",
      message: "This request conflicts with the current state of the resource.",
      status,
      requestId,
      details,
    });
  }

  if (status === 422) {
    return new ApiError({
      code: "validation",
      message: "Some fields need attention before this request can be completed.",
      status,
      requestId,
      details,
    });
  }

  if (status === 429) {
    return new ApiError({
      code: "rate_limited",
      message: "Too many requests were sent. Try again in a moment.",
      status,
      requestId,
      details,
    });
  }

  if (status >= 500) {
    return new ApiError({
      code: "server",
      message: "The admin service is temporarily unavailable. Try again shortly.",
      status,
      requestId,
      details,
    });
  }

  return new ApiError({
    code: "unknown",
    message: "The request could not be completed.",
    status,
    requestId,
    details,
  });
}
