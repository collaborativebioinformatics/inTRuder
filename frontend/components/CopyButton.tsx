"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Copy one string to the clipboard, and say what happened.
 *
 * Every identifier in this interface — motifs, coordinates, sample IDs — exists
 * to be pasted into something else, so the copy affordance sits next to the
 * value rather than behind a menu. The clipboard API is unavailable outside a
 * secure context, so failure is a state this renders rather than an exception it
 * swallows: the text stays selectable either way.
 */

type State = "idle" | "copied" | "failed";

const MESSAGE: Record<State, string> = {
  idle: "Copy",
  copied: "Copied",
  failed: "Select it",
};

export function CopyButton({
  text,
  label = "Copy",
  idleText = "Copy",
  className = "",
}: {
  text: string;
  /** What is being copied, for the accessible name: "Copy motif". */
  label?: string;
  /** Face of the button before it is pressed. */
  idleText?: string;
  className?: string;
}) {
  const [state, setState] = useState<State>("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), 1400);
  }

  return (
    <button
      type="button"
      onClick={copy}
      aria-label={label}
      title={state === "failed" ? "Clipboard unavailable — select the text instead" : label}
      className={`shrink-0 rounded-sm border border-hairline px-1.5 py-0.5 text-[10px] transition-colors hover:border-baseline hover:text-ink ${
        state === "copied" ? "text-ink" : "text-ink-muted"
      } ${className}`}
    >
      {state === "idle" ? idleText : MESSAGE[state]}
    </button>
  );
}
