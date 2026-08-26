"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import type { ViewFilters } from "./types";

/**
 * The one piece of state the chat and the controls both write to.
 *
 * This is the whole idea behind the interface: the agent's `set_view` tool and
 * the filter chips are two ways of editing the same object, so a question typed
 * into chat moves the same view a click would. Nothing here knows about the
 * agent — it just accepts patches.
 */

const EMPTY: ViewFilters = {};

interface ViewContextValue {
  filters: ViewFilters;
  /** Set of filter keys most recently changed by the agent, for highlighting. */
  agentTouched: Set<keyof ViewFilters>;
  patch: (next: ViewFilters, source?: "user" | "agent") => void;
  reset: () => void;
  focusLocus: (locusId: string | null) => void;
}

const ViewContext = createContext<ViewContextValue | null>(null);

function normalize(filters: ViewFilters): ViewFilters {
  // Nulls and falsey booleans mean "cleared" — drop them so the query string and
  // the chip row stay honest about what is actually active.
  const out: ViewFilters = {};
  for (const [key, value] of Object.entries(filters) as [keyof ViewFilters, unknown][]) {
    if (value === null || value === undefined) continue;
    if (typeof value === "boolean" && !value) continue;
    (out as Record<string, unknown>)[key] = value;
  }
  return out;
}

export function ViewProvider({ children }: { children: ReactNode }) {
  const [filters, setFilters] = useState<ViewFilters>(EMPTY);
  const [agentTouched, setAgentTouched] = useState<Set<keyof ViewFilters>>(new Set());

  const patch = useCallback((next: ViewFilters, source: "user" | "agent" = "user") => {
    setFilters((current) => normalize({ ...current, ...next }));
    setAgentTouched(
      source === "agent" ? new Set(Object.keys(next) as (keyof ViewFilters)[]) : new Set(),
    );
  }, []);

  const reset = useCallback(() => {
    setFilters(EMPTY);
    setAgentTouched(new Set());
  }, []);

  const focusLocus = useCallback((locusId: string | null) => {
    setFilters((current) => normalize({ ...current, focus_locus_id: locusId }));
  }, []);

  const value = useMemo(
    () => ({ filters, agentTouched, patch, reset, focusLocus }),
    [filters, agentTouched, patch, reset, focusLocus],
  );

  return <ViewContext.Provider value={value}>{children}</ViewContext.Provider>;
}

export function useView(): ViewContextValue {
  const context = useContext(ViewContext);
  if (!context) throw new Error("useView must be used inside <ViewProvider>");
  return context;
}
