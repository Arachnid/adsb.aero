import type { components } from "../types/api";

export type FlightDetail = components["schemas"]["FlightDetail"];
export type QueryRequest = components["schemas"]["QueryRequest"];
export type QueryResponse = components["schemas"]["QueryResponse"];
export type DataRange = components["schemas"]["DataRange"];
export type IcaoTypeStat = components["schemas"]["IcaoTypeStat"];
export type Airport = components["schemas"]["Airport"];

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
  opts: {
    endDate: string;
    startFrom?: string | null;
    cursor?: string | null;
    limit?: number;
    signal?: AbortSignal;
  },
): Promise<QueryResponse> {
  const body: QueryRequest = {
    end_date: opts.endDate,
    ...(opts.startFrom ? { start_from: opts.startFrom } : {}),
    window_days: 7,
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

export async function searchAirports(
  q: string,
  opts: { limit?: number; signal?: AbortSignal } = {},
): Promise<Airport[]> {
  const params = new URLSearchParams({ q });
  if (opts.limit != null) params.set("limit", String(opts.limit));
  const res = await fetch(`/api/v1/airports/search?${params.toString()}`, {
    ...(opts.signal ? { signal: opts.signal } : {}),
  });
  if (!res.ok) await parseError(res);
  return res.json() as Promise<Airport[]>;
}

export async function getIcaoTypes(
  start: string,
  end: string,
  opts: { signal?: AbortSignal } = {},
): Promise<IcaoTypeStat[]> {
  const params = new URLSearchParams({ start, end });
  const res = await fetch(`/api/v1/icao-types?${params.toString()}`, {
    ...(opts.signal ? { signal: opts.signal } : {}),
  });
  if (!res.ok) await parseError(res);
  return res.json() as Promise<IcaoTypeStat[]>;
}
