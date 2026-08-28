import { API_BASE } from "./api";
import type { Dataset, DatasetRole, Upload, UploadListing } from "./types";

/**
 * The upload half of the API client.
 *
 * The browser posts to the backend directly — `NEXT_PUBLIC_API_BASE` is the URL
 * *your browser* resolves, never a container name — so the file never passes
 * through Next.js. That is what makes uploading behave identically under
 * `just dev` and under Docker: there is no proxy in the middle with its own body
 * limit, and nothing here has to know which one it is running in.
 */

/** What the server said went wrong, rather than a bare status code. */
async function detailOf(response: Response): Promise<string> {
  const text = await response.text().catch(() => "");
  try {
    return (JSON.parse(text) as { detail?: string }).detail ?? text;
  } catch {
    return text || `${response.status} ${response.statusText}`;
  }
}

export interface UploadProgress {
  /** Bytes accepted so far. */
  loaded: number;
  /** Total bytes, or 0 while the browser has not said. */
  total: number;
  /** Bytes per second over the whole transfer so far. */
  rate: number;
}

/**
 * Send one file, reporting progress as it goes.
 *
 * Uses XMLHttpRequest rather than fetch, and this is the only reason: fetch
 * exposes no upload progress event, and a multi-gigabyte VCF with no visible
 * progress is indistinguishable from a hung browser. The body is the file
 * itself, not a multipart form, so the server writes it once instead of
 * spooling it to a temporary file and copying it again.
 */
export function uploadFile(
  file: File,
  options: { onProgress?: (progress: UploadProgress) => void; signal?: AbortSignal } = {},
): Promise<Upload> {
  const { onProgress, signal } = options;

  return new Promise<Upload>((resolve, reject) => {
    const request = new XMLHttpRequest();
    const started = performance.now();

    request.open(
      "POST",
      `${API_BASE}/api/uploads?filename=${encodeURIComponent(file.name)}`,
    );
    request.setRequestHeader("Content-Type", "application/octet-stream");

    request.upload.onprogress = (event) => {
      const seconds = (performance.now() - started) / 1000;
      onProgress?.({
        loaded: event.loaded,
        total: event.lengthComputable ? event.total : file.size,
        rate: seconds > 0 ? event.loaded / seconds : 0,
      });
    };

    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        try {
          resolve(JSON.parse(request.responseText) as Upload);
        } catch {
          reject(new Error("The server's reply could not be read."));
        }
        return;
      }
      let detail = `${request.status} ${request.statusText}`;
      try {
        detail = (JSON.parse(request.responseText) as { detail?: string }).detail ?? detail;
      } catch {
        // Non-JSON error body; the status line is what we have.
      }
      reject(new Error(detail));
    };

    request.onerror = () =>
      reject(
        new Error(
          `Cannot reach the API at ${API_BASE}. Is the backend running?`,
        ),
      );
    // Cancelling is a normal outcome here, not a failure — the dialog treats an
    // AbortError as "back to the start" rather than as something to report.
    request.onabort = () => reject(new DOMException("Upload cancelled", "AbortError"));

    signal?.addEventListener("abort", () => request.abort(), { once: true });
    request.send(file);
  });
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) throw new Error(await detailOf(response));
  return response.json() as Promise<T>;
}

export const fetchUploads = (signal?: AbortSignal) =>
  json<UploadListing>("/api/uploads", { signal });

/**
 * Record a file that is already on this machine, without copying it.
 *
 * The server confines the path to its permitted roots — the data directory plus
 * anything in `UPLOAD_LINK_ROOTS` — so a rejection here is a configuration
 * answer, not a missing file, and the message says which.
 */
export const linkUpload = (path: string) =>
  json<Upload>("/api/uploads/link", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });

export interface RegisterOptions {
  name: string;
  title?: string;
  description?: string;
  /** "" registers a table the assistant can query but that no page reads. */
  role?: DatasetRole | "";
}

export const registerUpload = (uploadId: string, options: RegisterOptions) =>
  json<{ dataset: Dataset; upload: Upload }>(`/api/uploads/${uploadId}/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "", description: "", role: "", ...options }),
  });

export const deleteUpload = (uploadId: string) =>
  json<{ deleted: string; unregistered: string | null }>(`/api/uploads/${uploadId}`, {
    method: "DELETE",
  });

export const reloadRegistry = () =>
  json<{ available: string[]; roles: Record<string, string | null> }>(
    "/api/registry/reload",
    { method: "POST" },
  );

/* -------------------------------------------------------------------------- */

/** `1.4 GB`, `812 kB`. Decimal units, which is what a file manager shows. */
export function formatBytes(bytes: number): string {
  if (bytes < 1000) return `${bytes} B`;
  const units = ["kB", "MB", "GB", "TB"];
  let value = bytes / 1000;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}

/**
 * A dataset name the registry will accept, derived from a filename.
 *
 * Deliberately the same rule the server enforces (`^[a-z_][a-z0-9_]*$`), applied
 * here so a bad name is caught in the field rather than after uploading a
 * gigabyte and pressing Register.
 */
export const DATASET_NAME = /^[a-z_][a-z0-9_]*$/;

export function slugifyDatasetName(text: string): string {
  const slug = text
    .toLowerCase()
    .replace(/\.(parquet|csv|tsv|vcf|bcf)(\.gz)?$/, "")
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (!slug) return "";
  return DATASET_NAME.test(slug) ? slug : `upload_${slug}`;
}
