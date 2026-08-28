"use client";

import type {
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
} from "react";

/**
 * The draggable seam between two workspace columns.
 *
 * It stands in for the hairline border the neighbouring column used to draw, so
 * the layout reads exactly as it did until you reach for it: a 1px rule, with a
 * 13px hit area straddling it and a thicker rule on hover or keyboard focus.
 *
 * The parent owns the width and this only proposes one, because the clamp
 * depends on what the other pane holds and on how much room the frame has left
 * — neither of which the seam can see.
 */

const STEP = 16;
const COARSE_STEP = 64;

interface PaneDividerProps {
  /** Width of the pane this seam sizes, in px. Reported to assistive tech. */
  width: number;
  min: number;
  /** May be Infinity before the frame has been measured. */
  max: number;
  /** Which side of the seam that pane sits on — it fixes the drag direction. */
  side: "left" | "right";
  label: string;
  onResize: (width: number) => void;
  onDraggingChange: (dragging: boolean) => void;
  onReset: () => void;
}

export function PaneDivider({
  width,
  min,
  max,
  side,
  label,
  onResize,
  onDraggingChange,
  onReset,
}: PaneDividerProps) {
  // Dragging right widens a left-hand pane and narrows a right-hand one.
  const sign = side === "left" ? 1 : -1;

  function handlePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    // Otherwise the browser starts selecting text in whatever the drag crosses.
    // That also suppresses the mousedown that would have moved focus here, so
    // the seam has to take it itself — a click then the arrow keys is the whole
    // point of making it focusable.
    event.preventDefault();
    const handle = event.currentTarget;
    handle.focus();
    const startX = event.clientX;
    const startWidth = width;

    // Capture keeps the move events coming from the seam even once the pointer
    // has left it, which it does immediately.
    handle.setPointerCapture(event.pointerId);
    onDraggingChange(true);

    const move = (moved: PointerEvent) =>
      onResize(startWidth + (moved.clientX - startX) * sign);
    const end = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", end);
      handle.removeEventListener("pointercancel", end);
      onDraggingChange(false);
    };

    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
  }

  function handleKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    const step = event.shiftKey ? COARSE_STEP : STEP;
    if (event.key === "ArrowLeft") onResize(width - step * sign);
    else if (event.key === "ArrowRight") onResize(width + step * sign);
    else if (event.key === "Home" || event.key === "Enter") onReset();
    else return;
    event.preventDefault();
  }

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={Math.round(width)}
      aria-valuemin={Math.round(min)}
      aria-valuemax={Number.isFinite(max) ? Math.round(max) : undefined}
      tabIndex={0}
      title={`${label} — drag or use the arrow keys; double-click to reset.`}
      onPointerDown={handlePointerDown}
      onKeyDown={handleKeyDown}
      onDoubleClick={onReset}
      className="group relative z-10 hidden cursor-col-resize touch-none outline-none lg:block"
      style={{ background: "var(--hairline)" }}
    >
      {/* The seam is a hairline; the thing you have to hit is not. */}
      <span aria-hidden className="absolute inset-y-0 -left-1.5 -right-1.5" />
      {/* Hover and focus thicken the rule rather than adding a ring: the seam is
          1px of chrome between two scrolling columns, and an outline drawn the
          full height of the window would read as a border on one of them. */}
      <span
        aria-hidden
        className="absolute inset-y-0 -left-px -right-px opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
        style={{ background: "var(--baseline)" }}
      />
    </div>
  );
}
