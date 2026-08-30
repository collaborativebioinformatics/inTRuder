/**
 * Which datasets this browser has switched off.
 *
 * The state is local on purpose. One backend serves many people, so "is the demo
 * data showing?" cannot live on the server without one person's switch moving
 * everybody else's screen. What is stored here is only what somebody explicitly
 * flipped; the default — a synthetic fixture switches itself off once real data
 * is driving a surface — is computed by the server, which is the only side that
 * knows what data exists. Every request carries the overrides in a header, and
 * the server folds the two together.
 *
 * Read straight out of `localStorage` on each call rather than mirrored into
 * React state. It is a synchronous read of a handful of keys, and it means there
 * is no window during startup where a fetch goes out before the provider has
 * loaded — the first request of the session already carries the right switches.
 */

const KEY = "intruder-dataset-switches";

/** name -> the position somebody put it in. Absent means "use the default". */
export type Overrides = Record<string, boolean>;

export function readOverrides(): Overrides {
  // Also the server-render path, where there is no localStorage and no fetch.
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return {};
    const out: Overrides = {};
    for (const [name, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof value === "boolean") out[name] = value;
    }
    return out;
  } catch {
    // A private window, blocked site data, or something else's key under ours.
    // Defaults are a correct answer, so this is not worth surfacing.
    return {};
  }
}

/**
 * Move one switch. `null` forgets the choice, which puts the dataset back on
 * whatever the server says the default is — not on today's value of it, so a
 * fixture reset to default goes back to switching itself off when real data
 * arrives.
 */
export function writeOverride(name: string, enabled: boolean | null): Overrides {
  const overrides = readOverrides();
  if (enabled === null) delete overrides[name];
  else overrides[name] = enabled;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(overrides));
  } catch {
    // Non-fatal: the switch holds for this page, it just is not remembered.
  }
  return overrides;
}

/**
 * The switches as request headers, to merge into every fetch. Empty when nobody
 * has touched anything, so a fresh browser sends no header at all and gets the
 * server's defaults.
 */
export function switchHeaders(): Record<string, string> {
  const entries = Object.entries(readOverrides());
  if (entries.length === 0) return {};
  return {
    "X-Dataset-Switches": entries
      .map(([name, enabled]) => `${name}=${enabled ? "on" : "off"}`)
      .join(","),
  };
}
