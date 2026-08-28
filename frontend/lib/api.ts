import { switchHeaders } from "./switches";
import type {
  AgentEvent,
  Dataset,
  LociResponse,
  LocusDetail,
  StrchiveLociResponse,
  StrchiveMatchesResponse,
  StrchiveSummary,
  Summary,
  ViewFilters,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ?? "http://localhost:8000";

/**
 * An API response that arrived and said no — as opposed to a network failure,
 * which is the other thing a rejected fetch means and needs telling apart. A 503
 * carrying "no candidate-locus dataset is available" is the server working
 * correctly and reporting a state the reader can fix; "start the backend" is the
 * wrong advice for it.
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function getJSON<T>(path: string, signal?: AbortSignal): Promise<T> {
  // Every read carries this browser's dataset switches, so a table somebody has
  // switched off is one the server does not draw from — for them, and only for
  // them. See lib/switches.ts.
  const response = await fetch(`${API_BASE}${path}`, { signal, headers: switchHeaders() });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    // FastAPI puts the sentence worth reading in `detail`. Showing the raw JSON
    // instead buries it in punctuation.
    let detail = "";
    try {
      detail = String((JSON.parse(body) as { detail?: unknown }).detail ?? "");
    } catch {
      detail = body;
    }
    throw new ApiError(
      response.status,
      detail || `${response.status} ${response.statusText}`,
    );
  }
  return response.json() as Promise<T>;
}

function toQuery(filters: ViewFilters, extra: Record<string, string | number> = {}) {
  const params = new URLSearchParams();
  if (filters.novel_only) params.set("novel_only", "true");
  if (filters.disease_gene_only) params.set("disease_gene_only", "true");
  if (filters.chrom) params.set("chrom", filters.chrom);
  if (filters.region) params.set("region", filters.region);
  if (filters.motif_class) params.set("motif_class", filters.motif_class);
  if (filters.gene) params.set("gene", filters.gene);
  if (filters.gene_query) params.set("gene_query", filters.gene_query);
  if (filters.min_motif_len != null) params.set("min_motif_len", String(filters.min_motif_len));
  if (filters.min_samples != null) params.set("min_samples", String(filters.min_samples));
  if (filters.min_purity != null) params.set("min_purity", String(filters.min_purity));
  if (filters.novelty) params.set("novelty", filters.novelty);
  if (filters.platform_agreement) params.set("platform_agreement", filters.platform_agreement);
  if (filters.sample) params.set("sample", filters.sample);
  if (filters.strchive_status) params.set("strchive_status", filters.strchive_status);
  if (filters.min_insertion_purity != null) {
    params.set("min_insertion_purity", String(filters.min_insertion_purity));
  }
  if (filters.sort) params.set("sort", filters.sort);
  if (filters.sort_dir) params.set("sort_dir", filters.sort_dir);
  for (const [key, value] of Object.entries(extra)) params.set(key, String(value));
  return params.toString();
}

export const fetchSummary = (signal?: AbortSignal) => getJSON<Summary>("/api/summary", signal);

export const fetchLoci = (filters: ViewFilters, limit = 400, signal?: AbortSignal) =>
  getJSON<LociResponse>(
    `/api/loci?${toQuery(filters, { limit, include_strips: "true" })}`,
    signal,
  );

export const fetchLocus = (locusId: string, signal?: AbortSignal) =>
  getJSON<LocusDetail>(`/api/loci/${encodeURIComponent(locusId)}`, signal);

export interface Health {
  status: string;
  agent_enabled: boolean;
  llm: { provider: string; credential_present?: boolean; credential_env?: string | null };
  datasets: {
    available: string[];
    unavailable: { name: string; error: string }[];
    /** Present on this backend; absent on an older one. */
    disabled?: string[];
  };
}

export const fetchHealth = (signal?: AbortSignal) => getJSON<Health>("/api/health", signal);

/**
 * Every registered dataset, including the ones switched off or missing their
 * file, plus which table currently holds each role for this caller.
 */
export const fetchDatasets = (signal?: AbortSignal) =>
  getJSON<{ datasets: Dataset[]; roles: Record<string, string | null> }>(
    "/api/datasets",
    signal,
  );

/* -------------------------------------------------------------------------- */
/* STRchive                                                                    */
/* -------------------------------------------------------------------------- */

export const fetchStrchiveSummary = (signal?: AbortSignal) =>
  getJSON<StrchiveSummary>("/api/strchive/summary", signal);

export const fetchStrchiveLoci = (
  options: { novel_in_reference?: boolean; evidence?: string; inheritance?: string; q?: string } = {},
  signal?: AbortSignal,
) => {
  const params = new URLSearchParams();
  if (options.novel_in_reference) params.set("novel_in_reference", "true");
  if (options.evidence) params.set("evidence", options.evidence);
  if (options.inheritance) params.set("inheritance", options.inheritance);
  if (options.q) params.set("q", options.q);
  const query = params.toString();
  return getJSON<StrchiveLociResponse>(
    `/api/strchive/loci${query ? `?${query}` : ""}`,
    signal,
  );
};

/**
 * Our own candidates that landed on a disease locus. Resolves with
 * `available: false` rather than throwing when the screened callset is not
 * registered yet — not-yet-run is a state the page renders, not an error.
 */
export const fetchStrchiveMatches = (signal?: AbortSignal) =>
  getJSON<StrchiveMatchesResponse>("/api/strchive/matches", signal);

/**
 * Stream one agent turn. Parses the SSE frames emitted by app/agent.py and
 * invokes `onEvent` for each. Resolves when the stream closes.
 */
export async function streamChat(
  messages: { role: "user" | "assistant"; content: string }[],
  onEvent: (event: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    // The agent is told about the datasets this browser has switched on, and no
    // others — a fixture hidden from the page but left in the schema prompt is
    // one the model would happily answer a cohort question from.
    headers: { "Content-Type": "application/json", ...switchHeaders() },
    body: JSON.stringify({ messages }),
    signal,
  });

  if (!response.ok || !response.body) {
    throw new Error(`Chat request failed: ${response.status} ${response.statusText}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      try {
        onEvent(JSON.parse(line.slice(5).trim()) as AgentEvent);
      } catch {
        // A malformed frame should not kill the stream.
      }
    }
  }
}
