import { appEnv } from "@/config/env";
import { ApiError, getRequestId, mapHttpStatusToApiError } from "./errors";

const DEFAULT_TIMEOUT_MS = 15_000;

export type ApiSuccess<T> = {
  ok: true;
  data: T;
  status: number;
  requestId: string | null;
  headers: Headers;
};

export type ApiFailure = {
  ok: false;
  error: ApiError;
  status: number | null;
  requestId: string | null;
};

export type ApiResult<T> = ApiSuccess<T> | ApiFailure;

export interface ApiRequestOptions extends Omit<RequestInit, "body"> {
  body?: BodyInit | object | null;
  timeoutMs?: number;
}

export interface ApiClient {
  request: <T>(path: string, options?: ApiRequestOptions) => Promise<ApiResult<T>>;
}

export function createApiClient(options?: {
  baseUrl?: string | null;
  credentials?: RequestCredentials;
  fetchImpl?: typeof fetch;
}) {
  const baseUrl = options?.baseUrl ?? appEnv.apiBaseUrl;
  const credentials = options?.credentials ?? "include";
  const fetchImpl = options?.fetchImpl ?? fetch;

  const request = async <T>(path: string, options: ApiRequestOptions = {}) => {
    if (!baseUrl) {
      return {
        ok: false,
        error: new ApiError({
          code: "configuration",
          message:
            "Admin API base URL is not configured. Set VITE_API_BASE_URL before using production data transport.",
        }),
        status: null,
        requestId: null,
      };
    }

    const controller = new AbortController();
    const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    const timeoutHandle = setTimeout(() => controller.abort(), timeoutMs);

    const headers = new Headers(options.headers);
    headers.set("accept", "application/json");

    let body: BodyInit | undefined;
    if (options.body instanceof FormData || options.body instanceof URLSearchParams) {
      body = options.body;
    } else if (options.body != null) {
      headers.set("content-type", "application/json");
      body = JSON.stringify(options.body);
    }

    try {
      const response = await fetchImpl(new URL(path, baseUrl), {
        ...options,
        body,
        credentials,
        headers,
        signal: combineAbortSignals(options.signal, controller.signal),
      });

      clearTimeout(timeoutHandle);
      const requestId = getRequestId(response.headers);
      const payload = await readJsonSafely(response);

      if (!response.ok) {
        return {
          ok: false,
          error: mapHttpStatusToApiError(response.status, requestId, payload),
          status: response.status,
          requestId,
        };
      }

      return {
        ok: true,
        data: payload as T,
        status: response.status,
        requestId,
        headers: response.headers,
      };
    } catch (error) {
      clearTimeout(timeoutHandle);

      if (error instanceof DOMException && error.name === "AbortError") {
        return {
          ok: false,
          error: new ApiError({
            code: "timeout",
            message: "The request took too long to complete.",
          }),
          status: null,
          requestId: null,
        };
      }

      return {
        ok: false,
        error: new ApiError({
          code: "network",
          message: "The admin service could not be reached. Check your connection and try again.",
        }),
        status: null,
        requestId: null,
      };
    }
  };

  return { request };
}

function combineAbortSignals(
  externalSignal: AbortSignal | null | undefined,
  internalSignal: AbortSignal,
): AbortSignal {
  if (!externalSignal) return internalSignal;
  if (externalSignal.aborted) return externalSignal;

  const bridge = new AbortController();
  const abortBridge = () => bridge.abort();

  externalSignal.addEventListener("abort", abortBridge, { once: true });
  internalSignal.addEventListener("abort", abortBridge, { once: true });

  return bridge.signal;
}

async function readJsonSafely(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) return null;

  try {
    return await response.json();
  } catch {
    return null;
  }
}
