"use client";

import { useCallback, useRef, useState } from "react";

/**
 * The rectangle you drop a file onto.
 *
 * One component for both places it appears — inside the upload dialog, and
 * inline on the Datasets surface when nothing is registered yet — so the two
 * cannot drift into looking like different features.
 *
 * Deliberately hairline and recessive rather than a filled call to action. The
 * warm `--novel` in this interface is a *data* encoding (absent from every
 * catalog versus already catalogued); spending it on a control would put the
 * loudest colour on the page on a button rather than on the finding, and every
 * barcode below would have to compete with it.
 */
export function DropZone({
  accepted,
  maxMb,
  onFile,
  compact = false,
}: {
  /** Extensions the server will take, e.g. [".parquet", ".vcf.gz"]. */
  accepted: string[];
  maxMb: number;
  onFile: (file: File) => void;
  /** Shorter, for the inline placement where it is not the only thing on screen. */
  compact?: boolean;
}) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const take = useCallback(
    (files: FileList | null) => {
      // One at a time: each upload ends in a decision about what the file is and
      // what to call it, and a queue of those is a worse experience than two
      // trips through a dialog that takes four seconds.
      const file = files?.[0];
      if (file) onFile(file);
    },
    [onFile],
  );

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => {
        event.preventDefault();
        setOver(false);
        take(event.dataTransfer.files);
      }}
      className={`rounded-lg border border-dashed text-center transition-colors ${
        compact ? "px-4 py-6" : "px-6 py-10"
      }`}
      style={{
        borderColor: over ? "var(--baseline)" : "var(--hairline)",
        background: over ? "var(--surface-raised)" : "transparent",
      }}
    >
      <p className="text-sm text-ink">
        {over ? "Release to upload" : "Drop a file here"}
      </p>
      <p className="mt-1 text-[11px] text-ink-muted">
        or{" "}
        <button
          type="button"
          onClick={() => input.current?.click()}
          className="underline underline-offset-2 hover:text-ink"
        >
          choose one from your computer
        </button>
      </p>
      <p className="mt-3 text-[11px] text-ink-muted">
        <span className="tabular">{accepted.join(" · ")}</span>
        {maxMb > 0 && <> · up to {maxMb >= 1024 ? `${Math.round(maxMb / 1024)} GB` : `${maxMb} MB`}</>}
      </p>
      <input
        ref={input}
        type="file"
        accept={accepted.join(",")}
        className="sr-only"
        onChange={(event) => {
          take(event.target.files);
          // Reset, so choosing the same file twice in a row fires again.
          event.target.value = "";
        }}
      />
    </div>
  );
}
