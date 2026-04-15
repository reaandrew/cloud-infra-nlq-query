/**
 * Typed HTTP client for the cinq NLQ API.
 *
 * Base URL is read from VITE_API_BASE_URL at build time, with a sensible
 * default for local dev. The API key (when needed) is read from
 * localStorage at call time so the user can paste it into the modal
 * without rebuilding.
 */

const DEFAULT_BASE = "https://api.nlq.demos.apps.equal.expert";

export const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ??
  DEFAULT_BASE;

const API_KEY_STORAGE = "cinq-api-key";

export function getStoredApiKey(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(API_KEY_STORAGE) ?? "";
}

export function setStoredApiKey(value: string): void {
  if (typeof window === "undefined") return;
  if (value) {
    window.localStorage.setItem(API_KEY_STORAGE, value);
  } else {
    window.localStorage.removeItem(API_KEY_STORAGE);
  }
}

// ---------- response types ----------

export interface OverviewStats {
  total_resources: number;
  distinct_accounts: number;
  distinct_resource_types: number;
  distinct_regions: number;
  first_seen_at: string | null;
  last_seen_at: string | null;
  athena_query_id?: string;
}

export interface TypeCount {
  resource_type: string;
  resource_count: number;
}

export interface AccountCount {
  account_id: string;
  resource_count: number;
  distinct_resource_types: number;
  distinct_regions: number;
}

export interface RegionCount {
  aws_region: string;
  resource_count: number;
  distinct_accounts: number;
  distinct_resource_types: number;
}

export interface RetrievedSchema {
  resource_type: string;
  service: string | null;
  category: string | null;
  field_count: number | null;
  distance: number;
}

export interface NlqRequest {
  question: string;
  top_k?: number;
  dry_run?: boolean;
}

export interface NlqResponse {
  question: string;
  sql: string;
  retrieved_schemas: RetrievedSchema[];
  columns?: string[];
  rows: Record<string, string>[];
  row_count: number;
  athena_query_id: string | null;
  athena_stats?: {
    data_scanned_bytes?: number | null;
    engine_execution_ms?: number | null;
    total_execution_ms?: number | null;
    query_queue_ms?: number | null;
    query_planning_ms?: number | null;
  };
  dry_run?: boolean;
  timings: {
    embed_ms?: number;
    retrieve_ms?: number;
    generate_ms?: number;
    athena_ms?: number;
    total_ms: number;
  };
}

export interface ApiErrorBody {
  error: string;
  detail?: string;
  sql?: string;
  retrieved_schemas?: RetrievedSchema[];
  timings?: NlqResponse["timings"];
}

export class ApiError extends Error {
  status: number;
  body: ApiErrorBody;
  constructor(status: number, body: ApiErrorBody) {
    super(body.error || `HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

// ---------- low-level fetch ----------

async function jsonFetch<T>(path: string, init?: RequestInit & { authed?: boolean }): Promise<T> {
  const url = `${API_BASE_URL}${path}`;
  const headers: Record<string, string> = {
    "content-type": "application/json",
    accept: "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (init?.authed) {
    const key = getStoredApiKey();
    if (!key) {
      throw new ApiError(401, { error: "no API key set" });
    }
    headers["x-api-key"] = key;
  }

  const res = await fetch(url, { ...init, headers });
  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = { error: text };
    }
  }
  if (!res.ok) {
    throw new ApiError(res.status, (body as ApiErrorBody) ?? { error: `HTTP ${res.status}` });
  }
  return body as T;
}

// ---------- typed wrappers ----------

export const api = {
  overview: () => jsonFetch<OverviewStats>("/stats/overview"),
  byType: (limit = 25) =>
    jsonFetch<{ items: TypeCount[]; limit: number }>(`/stats/by-type?limit=${limit}`),
  byAccount: (limit = 25) =>
    jsonFetch<{ items: AccountCount[]; limit: number }>(`/stats/by-account?limit=${limit}`),
  byRegion: () => jsonFetch<{ items: RegionCount[] }>("/stats/by-region"),
  ask: (req: NlqRequest) =>
    jsonFetch<NlqResponse>("/nlq", {
      method: "POST",
      body: JSON.stringify(req),
      authed: true,
    }),
};
