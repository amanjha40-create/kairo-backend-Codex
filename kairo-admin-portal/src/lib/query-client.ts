import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { ApiError } from "./api/errors";

const DEFAULT_QUERY_STALE_TIME_MS = 60_000;

export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError) {
    if (["unauthorized", "forbidden", "validation", "not_found"].includes(error.code)) {
      return false;
    }
  }

  return failureCount < 2;
}

export function createAppQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: shouldRetryQuery,
        staleTime: DEFAULT_QUERY_STALE_TIME_MS,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        refetchOnReconnect: true,
      },
      mutations: {
        retry: false,
      },
    },
    queryCache: new QueryCache(),
    mutationCache: new MutationCache(),
  });
}
