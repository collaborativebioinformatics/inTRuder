"use client";

import { useEffect, useState } from "react";

/**
 * Dragging a file anywhere over the window arms the upload.
 *
 * Two details that this gets wrong if written the obvious way:
 *
 * `dragleave` fires on the window every time the pointer crosses into a child
 * element, so a naive enter/leave pair makes the overlay strobe as you move
 * across the page. A depth counter — increment on enter, decrement on leave —
 * only reaches zero when the pointer has genuinely left.
 *
 * And `dataTransfer.types` is checked for "Files", so dragging selected text or
 * a link across the page does not offer to upload it.
 */
export function useWindowFileDrop(onDrop: (file: File) => void, enabled = true): boolean {
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    let depth = 0;

    const carriesFiles = (event: DragEvent) =>
      Array.from(event.dataTransfer?.types ?? []).includes("Files");

    const onEnter = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      depth += 1;
      setDragging(true);
    };

    const onOver = (event: DragEvent) => {
      // Without this the browser navigates to the file instead of letting the
      // page have it — the default action for a dropped file is to open it.
      if (carriesFiles(event)) event.preventDefault();
    };

    const onLeave = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setDragging(false);
    };

    const onDropped = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      depth = 0;
      setDragging(false);
      const file = event.dataTransfer?.files?.[0];
      if (file) onDrop(file);
    };

    window.addEventListener("dragenter", onEnter);
    window.addEventListener("dragover", onOver);
    window.addEventListener("dragleave", onLeave);
    window.addEventListener("drop", onDropped);
    return () => {
      window.removeEventListener("dragenter", onEnter);
      window.removeEventListener("dragover", onOver);
      window.removeEventListener("dragleave", onLeave);
      window.removeEventListener("drop", onDropped);
    };
  }, [onDrop, enabled]);

  return dragging;
}
