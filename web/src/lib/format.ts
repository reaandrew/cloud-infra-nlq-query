/** Format a number with thousand separators. */
export function fmtNumber(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("en-GB");
}

/** Format milliseconds compactly (e.g. 1.2 s, 950 ms). */
export function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

/** Format an ISO-ish timestamp into `YYYY-MM-DD HH:mm` UTC. */
export function fmtTimestamp(ts: string | null | undefined): string {
  if (!ts) return "—";
  // Athena returns "2026-04-13 05:14:02.335000"; trim to minute precision.
  return ts.slice(0, 16).replace("T", " ");
}

/** Truncate the middle of a long string (ARNs, source keys). */
export function truncateMiddle(s: string, max = 60): string {
  if (s.length <= max) return s;
  const head = Math.ceil((max - 1) / 2);
  const tail = max - 1 - head;
  return `${s.slice(0, head)}…${s.slice(-tail)}`;
}
