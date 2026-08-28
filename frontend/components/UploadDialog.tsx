"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { DropZone } from "@/components/DropZone";
import {
  DATASET_NAME,
  formatBytes,
  linkUpload,
  registerUpload,
  slugifyDatasetName,
  uploadFile,
  type UploadProgress,
} from "@/lib/uploads";
import type { Dataset, DatasetRole, Upload, UploadListing } from "@/lib/types";
import { useView } from "@/lib/viewStore";

/**
 * The upload window: drop a file, watch it arrive, say what it is.
 *
 * A native <dialog> with showModal(), which brings the focus trap, Escape, the
 * inert background and ::backdrop with it — all the things a hand-rolled overlay
 * gets subtly wrong.
 *
 * The four steps are one state machine rather than a pile of booleans, because
 * they are genuinely exclusive and the interesting bugs in an upload dialog are
 * all two states being true at once: a progress bar over a finished upload, a
 * confirm form for a file that failed.
 */

type Stage =
  | { name: "idle" }
  | { name: "uploading"; file: File; progress: UploadProgress }
  | { name: "confirm"; upload: Upload }
  | { name: "done"; upload: Upload; dataset: Dataset | null }
  | { name: "error"; message: string };

const ROLE_LABELS: Record<DatasetRole, string> = {
  loci: "Candidate loci — drives the catalog, the funnel and the barcodes",
  segments: "Per-allele repeat structure — draws the barcodes",
};

function rateOf(progress: UploadProgress): string {
  if (progress.rate <= 0) return "";
  return ` · ${formatBytes(progress.rate)}/s`;
}

/** The file's own summary line: what it is, in its own terms. */
function FileSummary({ upload }: { upload: Upload }) {
  const { inspect } = upload;
  const parts = [formatBytes(upload.bytes)];

  if (upload.kind === "variants") {
    if (inspect.n_samples) parts.push(`${inspect.n_samples} samples`);
    if (inspect.sources?.length) parts.push(inspect.sources.join(", "));
    if (inspect.merged) parts.push("merged callset");
  } else if (inspect.readable) {
    parts.push(`${inspect.n_rows?.toLocaleString()} rows`);
    parts.push(`${inspect.columns?.length} columns`);
  }

  return (
    <div className="space-y-1">
      <p className="tabular text-sm text-ink">{upload.filename}</p>
      <p className="text-[11px] text-ink-muted">
        {parts.join(" · ")}
        {upload.linked && " · read in place, not copied"}
      </p>
    </div>
  );
}

export function UploadDialog({
  open,
  onClose,
  initialFile,
  listing,
  onChanged,
}: {
  open: boolean;
  onClose: () => void;
  /** A file dropped onto the window, which opens this already uploading. */
  initialFile?: File | null;
  listing: UploadListing | null;
  /** Something was registered or removed — the registry has changed. */
  onChanged: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const abort = useRef<AbortController | null>(null);
  const { patch } = useView();

  const [stage, setStage] = useState<Stage>({ name: "idle" });
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [role, setRole] = useState<DatasetRole | "">("");
  const [busy, setBusy] = useState(false);

  const accepted = listing?.accepted ?? [".parquet", ".csv", ".tsv", ".vcf", ".vcf.gz"];
  const maxMb = listing?.max_upload_mb ?? 0;

  /* --- opening and closing ------------------------------------------------ */

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);

  const reset = useCallback(() => {
    abort.current?.abort();
    abort.current = null;
    setStage({ name: "idle" });
    setPath("");
    setName("");
    setTitle("");
    setDescription("");
    setRole("");
    setBusy(false);
  }, []);

  /* --- uploading ---------------------------------------------------------- */

  const begin = useCallback(
    async (file: File) => {
      const controller = new AbortController();
      abort.current = controller;
      setStage({
        name: "uploading",
        file,
        progress: { loaded: 0, total: file.size, rate: 0 },
      });

      try {
        const upload = await uploadFile(file, {
          signal: controller.signal,
          onProgress: (progress) =>
            setStage((current) =>
              current.name === "uploading" ? { ...current, progress } : current,
            ),
        });
        setName(upload.suggested_name ?? slugifyDatasetName(upload.filename));
        setTitle(upload.filename);
        setStage({ name: "confirm", upload });
      } catch (error) {
        // Cancelling is a normal outcome, not a failure to report back.
        if ((error as Error).name === "AbortError") setStage({ name: "idle" });
        else setStage({ name: "error", message: (error as Error).message });
      } finally {
        abort.current = null;
      }
    },
    [],
  );

  // A file dropped anywhere on the window opens this dialog already uploading.
  useEffect(() => {
    if (open && initialFile) void begin(initialFile);
    // `initialFile` is a fresh File object per drop, so this fires per drop.
  }, [open, initialFile, begin]);

  const link = useCallback(async () => {
    if (!path.trim()) return;
    setBusy(true);
    try {
      const upload = await linkUpload(path.trim());
      setName(upload.suggested_name ?? slugifyDatasetName(upload.filename));
      setTitle(upload.filename);
      setStage({ name: "confirm", upload });
    } catch (error) {
      setStage({ name: "error", message: (error as Error).message });
    } finally {
      setBusy(false);
    }
  }, [path]);

  /* --- registering -------------------------------------------------------- */

  const confirm = useCallback(async () => {
    if (stage.name !== "confirm") return;
    setBusy(true);
    try {
      const { dataset } = await registerUpload(stage.upload.id, {
        name,
        title,
        description,
        role,
      });
      setStage({ name: "done", upload: stage.upload, dataset });
      onChanged();
    } catch (error) {
      setStage({ name: "error", message: (error as Error).message });
    } finally {
      setBusy(false);
    }
  }, [stage, name, title, description, role, onChanged]);

  /* --- rendering ---------------------------------------------------------- */

  const nameValid = DATASET_NAME.test(name);
  const eligible = (stage.name === "confirm" && stage.upload.roles) || null;

  return (
    <dialog
      ref={dialog}
      onClose={() => {
        reset();
        onClose();
      }}
      onCancel={() => {
        reset();
        onClose();
      }}
      aria-labelledby="upload-heading"
      className="m-auto w-[min(34rem,calc(100vw-2rem))] rounded-xl border border-hairline p-0 text-ink backdrop:bg-black/40"
      style={{ background: "var(--surface)" }}
    >
      <div className="space-y-4 p-5">
        <header className="flex items-baseline justify-between gap-4">
          <h2 id="upload-heading" className="text-sm font-medium text-ink">
            {stage.name === "done" ? "Added" : "Add data"}
          </h2>
          <button
            type="button"
            onClick={() => dialog.current?.close()}
            className="text-[11px] text-ink-muted hover:text-ink"
          >
            Close
          </button>
        </header>

        {/* ---- Idle: drop a file, or point at one already on this machine --- */}
        {stage.name === "idle" && (
          <>
            <DropZone accepted={accepted} maxMb={maxMb} onFile={(file) => void begin(file)} />

            <div className="space-y-2 border-t border-hairline pt-4">
              <label htmlFor="upload-path" className="block text-[11px] text-ink-secondary">
                Or read a file already on this machine — no copy is made. The
                answer for a callset that is tens of gigabytes, and for running
                without Docker at all.
              </label>
              <div className="flex gap-2">
                <input
                  id="upload-path"
                  value={path}
                  onChange={(event) => setPath(event.target.value)}
                  onKeyDown={(event) => event.key === "Enter" && void link()}
                  placeholder="data/sv_output/merged.vcf.gz"
                  className="tabular min-w-0 flex-1 rounded-md border border-hairline px-2 py-1.5 text-xs outline-none focus:border-baseline"
                  style={{ background: "var(--surface-raised)" }}
                />
                <button
                  type="button"
                  onClick={() => void link()}
                  disabled={!path.trim() || busy}
                  className="rounded-md border border-hairline px-3 py-1.5 text-xs text-ink-secondary transition-colors hover:border-baseline hover:text-ink disabled:opacity-40"
                >
                  Read
                </button>
              </div>
            </div>
          </>
        )}

        {/* ---- Uploading ---------------------------------------------------- */}
        {stage.name === "uploading" && (
          <div className="space-y-3">
            <p className="tabular text-sm text-ink">{stage.file.name}</p>
            <div
              className="h-1.5 overflow-hidden rounded-full"
              style={{ background: "var(--hairline)" }}
            >
              <div
                className="h-full rounded-full transition-[width] duration-150"
                style={{
                  width: `${
                    stage.progress.total
                      ? (stage.progress.loaded / stage.progress.total) * 100
                      : 0
                  }%`,
                  background: "var(--step-3)",
                }}
              />
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <p className="tabular text-[11px] text-ink-muted">
                {formatBytes(stage.progress.loaded)} / {formatBytes(stage.progress.total)}
                {rateOf(stage.progress)}
              </p>
              <button
                type="button"
                onClick={() => abort.current?.abort()}
                className="text-[11px] text-ink-muted hover:text-ink"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* ---- Confirm ------------------------------------------------------ */}
        {stage.name === "confirm" && (
          <div className="space-y-4">
            <FileSummary upload={stage.upload} />

            {stage.upload.kind === "variants" ? (
              <>
                <p className="text-[11px] leading-relaxed text-ink-secondary">
                  Stored, and the assistant can now be asked about it. It is not a
                  table: a VCF becomes candidate loci by running the TR-detection
                  step, not by being uploaded.
                </p>
                {stage.upload.inspect.samples?.length ? (
                  <p className="tabular text-[11px] leading-relaxed text-ink-muted">
                    {stage.upload.inspect.samples.join(" ")}
                    {stage.upload.inspect.samples_truncated && " …"}
                  </p>
                ) : null}
                <div className="flex justify-end">
                  <button
                    type="button"
                    onClick={() => {
                      onChanged();
                      setStage({ name: "done", upload: stage.upload, dataset: null });
                    }}
                    className="rounded-md border border-hairline px-3 py-1.5 text-xs text-ink transition-colors hover:border-baseline"
                    style={{ background: "var(--surface-raised)" }}
                  >
                    Done
                  </button>
                </div>
              </>
            ) : !stage.upload.inspect.readable ? (
              <p className="text-[11px] leading-relaxed" style={{ color: "var(--novel)" }}>
                The file arrived, but could not be read as {stage.upload.format}:{" "}
                {stage.upload.inspect.error}
              </p>
            ) : (
              <>
                <div className="space-y-3">
                  <div className="space-y-1">
                    <label htmlFor="ds-name" className="block text-[11px] text-ink-secondary">
                      Table name — what you and the assistant will call it in SQL
                    </label>
                    <input
                      id="ds-name"
                      value={name}
                      onChange={(event) => setName(event.target.value)}
                      className="tabular w-full rounded-md border px-2 py-1.5 text-xs outline-none"
                      style={{
                        background: "var(--surface-raised)",
                        borderColor: nameValid ? "var(--hairline)" : "var(--novel)",
                      }}
                    />
                    {!nameValid && (
                      <p className="text-[11px]" style={{ color: "var(--novel)" }}>
                        Lowercase letters, digits and underscores, starting with a
                        letter.
                      </p>
                    )}
                  </div>

                  <div className="space-y-1">
                    <label htmlFor="ds-desc" className="block text-[11px] text-ink-secondary">
                      What is in it? This is not documentation — it is what the
                      assistant reads when deciding whether this table can answer
                      a question.
                    </label>
                    <textarea
                      id="ds-desc"
                      rows={3}
                      value={description}
                      onChange={(event) => setDescription(event.target.value)}
                      placeholder="One row per candidate locus in our 12-genome cohort, screened against UCSC simpleRepeat."
                      className="w-full resize-y rounded-md border border-hairline px-2 py-1.5 text-xs outline-none focus:border-baseline"
                      style={{ background: "var(--surface-raised)" }}
                    />
                  </div>

                  {eligible && (
                    <fieldset className="space-y-1.5">
                      <legend className="text-[11px] text-ink-secondary">
                        Use it for
                      </legend>
                      {(["", "loci", "segments"] as const).map((option) => {
                        const missing = option ? eligible[option] : [];
                        const blocked = option !== "" && missing.length > 0;
                        return (
                          <label
                            key={option || "none"}
                            className={`flex items-start gap-2 text-[11px] ${
                              blocked ? "text-ink-muted" : "text-ink-secondary"
                            }`}
                          >
                            <input
                              type="radio"
                              name="ds-role"
                              checked={role === option}
                              disabled={blocked}
                              onChange={() => setRole(option)}
                              className="mt-0.5"
                            />
                            <span>
                              {option === ""
                                ? "Queries only — the assistant can read it, no page changes"
                                : ROLE_LABELS[option]}
                              {blocked && (
                                <span className="tabular block text-ink-muted">
                                  missing {missing.join(", ")}
                                </span>
                              )}
                            </span>
                          </label>
                        );
                      })}
                    </fieldset>
                  )}
                </div>

                <div className="flex items-center justify-end gap-2">
                  <button
                    type="button"
                    onClick={reset}
                    className="text-[11px] text-ink-muted hover:text-ink"
                  >
                    Start over
                  </button>
                  <button
                    type="button"
                    onClick={() => void confirm()}
                    disabled={!nameValid || busy}
                    className="rounded-md border border-hairline px-3 py-1.5 text-xs text-ink transition-colors hover:border-baseline disabled:opacity-40"
                    style={{ background: "var(--surface-raised)" }}
                  >
                    {busy ? "Registering…" : "Register"}
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        {/* ---- Done --------------------------------------------------------- */}
        {stage.name === "done" && (
          <div className="space-y-4">
            <FileSummary upload={stage.upload} />
            <p className="text-[11px] leading-relaxed text-ink-secondary">
              {stage.dataset ? (
                <>
                  Registered as <span className="tabular text-ink">{stage.dataset.name}</span>
                  {stage.dataset.role
                    ? ` — the ${stage.dataset.role} surface now reads it.`
                    : " — ask the assistant about it, or query it in SQL."}
                </>
              ) : (
                "The assistant knows this file is here. Ask it what the VCF contains."
              )}
            </p>
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={reset}
                className="text-[11px] text-ink-muted hover:text-ink"
              >
                Add another
              </button>
              <button
                type="button"
                onClick={() => {
                  patch({ page: "datasets" });
                  dialog.current?.close();
                }}
                className="rounded-md border border-hairline px-3 py-1.5 text-xs text-ink transition-colors hover:border-baseline"
                style={{ background: "var(--surface-raised)" }}
              >
                View datasets
              </button>
            </div>
          </div>
        )}

        {/* ---- Error -------------------------------------------------------- */}
        {stage.name === "error" && (
          <div className="space-y-4">
            {/* The server's own words. It knows things this dialog does not —
                which extensions it takes, what the size cap is set to, which
                directories it may read — and paraphrasing loses all of it. */}
            <p className="text-xs leading-relaxed" style={{ color: "var(--novel)" }}>
              {stage.message}
            </p>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={reset}
                className="rounded-md border border-hairline px-3 py-1.5 text-xs text-ink transition-colors hover:border-baseline"
                style={{ background: "var(--surface-raised)" }}
              >
                Try again
              </button>
            </div>
          </div>
        )}
      </div>
    </dialog>
  );
}
