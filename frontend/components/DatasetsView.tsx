"use client";

import { useEffect, useState } from "react";

import { DropZone } from "@/components/DropZone";
import { fetchDatasets } from "@/lib/api";
import { readOverrides, writeOverride, type Overrides } from "@/lib/switches";
import type { Dataset, Upload, UploadListing } from "@/lib/types";
import { deleteUpload, formatBytes } from "@/lib/uploads";

/**
 * The third surface: what data this deployment actually has, and which of it is
 * switched on.
 *
 * Until now the answer lived in `/api/health` and a log line, which meant the
 * only way to find out why a chart was empty was to read the terminal. It earns
 * a page as soon as uploading exists, because "did my file land, and is anything
 * reading it?" is the question every upload ends with.
 *
 * The honesty rule the rest of the interface follows applies here too: a dataset
 * whose file is missing is listed *with its reason*, not omitted. An absent row
 * reads as "you never added it"; a present row saying `file not found` reads as
 * what it is. A switched-off row gets the same treatment: it stays in the list,
 * greyed, saying it is off — because a demo fixture that vanished when real data
 * arrived would look like something broke.
 */

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="shrink-0 text-[11px] text-ink-muted">{label}</span>
      <span className="min-w-0 text-[11px] text-ink-secondary">{children}</span>
    </div>
  );
}

function RoleBadge({ role }: { role: string }) {
  if (!role) return null;
  return (
    <span
      className="rounded-full px-2 py-0.5 text-[11px]"
      style={{ background: "var(--surface-raised)", color: "var(--ink-secondary)" }}
      title={
        role === "loci"
          ? "The catalog, funnel and barcodes read this table."
          : "The per-allele barcodes are drawn from this table."
      }
    >
      {role}
    </span>
  );
}

/**
 * The switch itself. A real checkbox under a drawn track, so it is reachable by
 * keyboard and announced as what it is; the visible part is a sibling rather
 * than a replacement, because a `appearance-none` checkbox styled into a track
 * loses the focus ring that tells you where you are.
 */
function Switch({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
}) {
  return (
    <label
      className="group relative inline-flex shrink-0 cursor-pointer items-center"
      title={label}
    >
      <input
        type="checkbox"
        className="peer sr-only"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        aria-label={label}
      />
      <span
        aria-hidden="true"
        className="block h-[18px] w-8 rounded-full transition-colors peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2"
        style={{
          background: checked ? "var(--motif-1)" : "var(--baseline)",
          outlineColor: "var(--motif-1)",
        }}
      />
      <span
        aria-hidden="true"
        className="pointer-events-none absolute left-[3px] block h-3 w-3 rounded-full transition-transform"
        style={{
          background: "var(--surface-raised)",
          transform: checked ? "translateX(14px)" : "translateX(0)",
        }}
      />
    </label>
  );
}

function DatasetRow({
  dataset,
  enabled,
  overridden,
  onToggle,
  onReset,
}: {
  dataset: Dataset;
  /** Where this browser's switch stands. See `isOn` — deliberately not `dataset.enabled`. */
  enabled: boolean;
  /** Whether this browser has a stored choice, rather than following the default. */
  overridden: boolean;
  onToggle: (next: boolean) => void;
  onReset: () => void;
}) {
  // A generated manifest documents no columns, and that prose is what the
  // assistant is shown. Saying so is the nudge that turns an uploaded table into
  // one somebody can actually ask about.
  const documented = Object.values(dataset.column_docs).filter(
    (doc) => doc && doc !== "(undocumented)",
  ).length;

  return (
    <li
      className="flex items-start gap-3 border-b border-hairline py-3 last:border-b-0"
      style={{ opacity: enabled ? 1 : 0.55 }}
    >
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="tabular text-sm text-ink">{dataset.name}</span>
          <RoleBadge role={dataset.role} />
          {dataset.synthetic && (
            <span
              className="rounded-full px-2 py-0.5 text-[11px] font-medium"
              style={{ background: "var(--novel-soft)", color: "var(--novel)" }}
              title="Generated fixture, not a result."
            >
              Synthetic
            </span>
          )}
          <span className="tabular ml-auto text-[11px] text-ink-muted">
            {!enabled
              ? "off"
              : dataset.available
                ? `${dataset.n_rows?.toLocaleString()} rows · ${dataset.columns.length} columns`
                : "unavailable"}
          </span>
        </div>

        {!enabled ? (
          <p className="text-[11px] leading-relaxed text-ink-muted">
            Switched off in this browser — no page draws it, and the assistant is
            not told it exists.
            {overridden && (
              <>
                {" "}
                <button
                  type="button"
                  onClick={onReset}
                  className="underline underline-offset-2 transition-colors hover:text-ink"
                >
                  {dataset.default_enabled
                    ? "Back to the default (on)"
                    : "Back to the default (off)"}
                </button>
              </>
            )}
          </p>
        ) : dataset.available ? (
          <>
            <p className="line-clamp-2 text-[11px] leading-relaxed text-ink-secondary">
              {dataset.description || "No description."}
            </p>
            <Field label="manifest">
              <span className="tabular">{dataset.manifest_file}</span>
              {documented < dataset.columns.length && (
                <span className="text-ink-muted">
                  {" "}
                  · {dataset.columns.length - documented} of {dataset.columns.length} columns
                  undocumented, so the assistant only knows their names
                </span>
              )}
            </Field>
            {overridden && !dataset.default_enabled && (
              <p className="text-[11px] leading-relaxed text-ink-muted">
                On because you switched it on; it would default to off now that
                real data is loaded.{" "}
                <button
                  type="button"
                  onClick={onReset}
                  className="underline underline-offset-2 transition-colors hover:text-ink"
                >
                  Back to the default
                </button>
              </p>
            )}
          </>
        ) : (
          <p
            className="break-all text-[11px] leading-relaxed"
            style={{ color: "var(--novel)" }}
          >
            {dataset.error}
          </p>
        )}
      </div>

      <div className="pt-0.5">
        <Switch
          checked={enabled}
          onChange={onToggle}
          label={
            enabled
              ? `Switch ${dataset.name} off — this browser's pages and assistant stop reading it`
              : `Switch ${dataset.name} on`
          }
        />
      </div>
    </li>
  );
}

function UploadRow({ upload, onRemove }: { upload: Upload; onRemove: () => void }) {
  const { inspect } = upload;
  const detail =
    upload.kind === "variants"
      ? [
          inspect.n_samples ? `${inspect.n_samples} samples` : null,
          inspect.sources?.join(", ") || null,
          inspect.merged ? "merged callset" : null,
        ]
      : [
          inspect.readable ? `${inspect.n_rows?.toLocaleString()} rows` : "unreadable",
          upload.dataset ? `registered as ${upload.dataset}` : "not registered",
        ];

  return (
    <li className="flex items-baseline gap-3 border-b border-hairline py-2.5 last:border-b-0">
      <div className="min-w-0 flex-1 space-y-0.5">
        <p className="tabular truncate text-xs text-ink">{upload.filename}</p>
        <p className="text-[11px] text-ink-muted">
          {[formatBytes(upload.bytes), ...detail.filter(Boolean)].join(" · ")}
          {upload.linked && " · read in place"}
          {!upload.present && (
            <span style={{ color: "var(--novel)" }}> · the file has gone missing</span>
          )}
        </p>
      </div>
      <button
        type="button"
        onClick={onRemove}
        title={
          upload.linked
            ? "Forget this file. The original on disk is not touched."
            : "Delete this file and unregister its dataset."
        }
        className="shrink-0 text-[11px] text-ink-muted transition-colors hover:text-ink"
      >
        {upload.linked ? "Forget" : "Delete"}
      </button>
    </li>
  );
}

export function DatasetsView({
  listing,
  onUpload,
  onChanged,
}: {
  listing: UploadListing | null;
  /** Open the upload dialog. */
  onUpload: (file?: File) => void;
  /** Something changed on the server — refetch everything downstream. */
  onChanged: () => void;
}) {
  const [datasets, setDatasets] = useState<Dataset[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // This browser's stored choices, mirrored into state so flipping a switch
  // redraws. `localStorage` is the source of truth — see lib/switches.ts — and
  // it is read lazily rather than in an effect so the first fetch of the session
  // already carries the right header.
  const [overrides, setOverrides] = useState<Overrides>(readOverrides);
  useEffect(() => {
    const controller = new AbortController();
    fetchDatasets(controller.signal)
      .then((response) => setDatasets(response.datasets))
      .catch((err: Error) => {
        if (err.name !== "AbortError") setError(err.message);
      });
    return () => controller.abort();
    // `overrides` is a dependency because the response depends on it: the server
    // folds this browser's switches into every row's `enabled`.
  }, [listing, overrides]);

  const toggle = (name: string, enabled: boolean | null) => {
    setError(null);
    setOverrides(writeOverride(name, enabled));
    // Every number on every other surface is drawn from whichever table holds a
    // role, and this may just have changed which one that is.
    onChanged();
  };

  /**
   * Where a switch stands, worked out here rather than read off the response.
   * The two agree — the server folds in the same overrides — but the response is
   * one request behind a click, and a switch that visibly lags the finger that
   * moved it reads as a switch that did not take.
   */
  const isOn = (dataset: Dataset) => overrides[dataset.name] ?? dataset.default_enabled;

  const uploads = listing?.uploads ?? [];
  const off = datasets?.filter((dataset) => !isOn(dataset)).length ?? 0;

  return (
    <section aria-labelledby="datasets-heading" className="scroll-quiet min-h-0 overflow-y-auto">
      <header className="pb-3">
        <h2 id="datasets-heading" className="text-sm font-medium text-ink">
          Datasets{" "}
          <span className="tabular font-normal text-ink-muted">
            {datasets ? datasets.length : "…"}
            {off > 0 && ` · ${off} off`}
          </span>
        </h2>
        <p className="mt-1 text-[11px] leading-relaxed text-ink-muted">
          Every table the interface and the assistant can read. Each one is a YAML
          manifest in the registry directory — adding data is a file, never a code
          change.
        </p>
        <p className="mt-1 text-[11px] leading-relaxed text-ink-muted">
          The switch takes a table out of the whole interface: no page draws it,
          and the assistant is neither told it exists nor allowed to query it.
          Synthetic fixtures switch themselves off as soon as real data is
          driving a surface, and back on when none is — move a switch by hand and
          your choice holds instead. Switches are kept in this browser, so they
          are yours alone; nothing you turn off here changes what anyone else
          sees.
        </p>
      </header>

      {error && (
        <p className="pb-3 text-[11px]" style={{ color: "var(--novel)" }}>
          {error}
        </p>
      )}

      {datasets && datasets.length === 0 && (
        <div className="py-4">
          <DropZone
            accepted={listing?.accepted ?? []}
            maxMb={listing?.max_upload_mb ?? 0}
            onFile={(file) => onUpload(file)}
          />
        </div>
      )}

      {datasets && datasets.length > 0 && (
        <ul className="border-t border-hairline">
          {datasets.map((dataset) => (
            <DatasetRow
              key={dataset.name}
              dataset={dataset}
              enabled={isOn(dataset)}
              overridden={dataset.name in overrides}
              onToggle={(next) => toggle(dataset.name, next)}
              onReset={() => toggle(dataset.name, null)}
            />
          ))}
        </ul>
      )}

      <section className="mt-8" aria-labelledby="uploads-heading">
        <div className="flex items-baseline justify-between gap-3 pb-2">
          <h3 id="uploads-heading" className="text-sm font-medium text-ink">
            Uploaded files{" "}
            <span className="tabular font-normal text-ink-muted">{uploads.length}</span>
          </h3>
          <button
            type="button"
            onClick={() => onUpload()}
            className="rounded-md border border-hairline px-2.5 py-1 text-[11px] text-ink-secondary transition-colors hover:border-baseline hover:text-ink"
          >
            Upload
          </button>
        </div>

        {listing && (
          <p className="pb-2 text-[11px] leading-relaxed text-ink-muted">
            Files land in <span className="tabular break-all">{listing.directory}</span> — the
            bind mount under Docker, the repository&rsquo;s own{" "}
            <span className="tabular">data/</span> without it.
          </p>
        )}

        {uploads.length === 0 ? (
          <p className="border-t border-hairline pt-3 text-[11px] text-ink-muted">
            Nothing uploaded yet. Drop a file anywhere on this page.
          </p>
        ) : (
          <ul className="border-t border-hairline">
            {uploads.map((upload) => (
              <UploadRow
                key={upload.id}
                upload={upload}
                onRemove={() => {
                  void deleteUpload(upload.id).then(onChanged).catch(() => onChanged());
                }}
              />
            ))}
          </ul>
        )}
      </section>
    </section>
  );
}
