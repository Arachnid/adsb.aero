import type { components } from "../types/api";

export type FlightDetail = components["schemas"]["FlightDetail"];
export type QueryRequest = components["schemas"]["QueryRequest"];
export type QueryResponse = components["schemas"]["QueryResponse"];
export type DataRange = components["schemas"]["DataRange"];

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function parseError(res: Response): Promise<never> {
  let detail = res.statusText;
  try {
    const body = (await res.json()) as { detail?: string };
    if (typeof body.detail === "string") detail = body.detail;
  } catch {
    // ignore JSON parse failure; fall back to statusText
  }
  throw new ApiError(res.status, detail);
}

export async function postQuery(
  match: QueryRequest["match"],
  opts: { cursor?: string | null; limit?: number; signal?: AbortSignal } = {},
): Promise<QueryResponse> {
  const body: QueryRequest = {
    match: match ?? null,
    limit: opts.limit ?? 100,
    include_path: true,
    ...(opts.cursor ? { cursor: opts.cursor } : {}),
  };
  const res = await fetch("/api/v1/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    ...(opts.signal ? { signal: opts.signal } : {}),
  });
  if (!res.ok) await parseError(res);
  return res.json() as Promise<QueryResponse>;
}

export async function getFlight(
  flightId: string,
  opts: { signal?: AbortSignal } = {},
): Promise<FlightDetail> {
  const res = await fetch(`/api/v1/flights/${encodeURIComponent(flightId)}`, {
    ...(opts.signal ? { signal: opts.signal } : {}),
  });
  if (!res.ok) await parseError(res);
  return res.json() as Promise<FlightDetail>;
}

export async function getDataRange(): Promise<DataRange> {
  const res = await fetch("/api/v1/data-range");
  if (!res.ok) await parseError(res);
  return res.json() as Promise<DataRange>;
}
