import { useEffect, useState } from "react";
import type { JobResponse } from "../lib/api";
import {
  STAGES,
  TOTAL_ESTIMATED_MS,
  deriveStageRender,
  isPollStale,
  totalElapsedMs,
} from "../lib/progress";

/**
 * Full-width sticky progress bar under the top nav during a query.
 *
 * Uses the same hybrid real-plus-synthetic derivation as the in-panel
 * QueryProgress card, so the two surfaces never disagree. Shows a subtle
 * "reconnecting…" hint when the most recent poll is more than 3 seconds
 * old, since that's the only moment where the only thing moving is the
 * synthetic fallback.
 */

interface Props {
  running: boolean;
  job: JobResponse | null;
  submittedAtMs: number;
  lastPollAtMs: number;
}

export function StickyProgressBar({ running, job, submittedAtMs, lastPollAtMs }: Props) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => setNow(Date.now()), 50);
    return () => window.clearInterval(id);
  }, [running]);

  if (!running) return null;

  const stale = isPollStale(job, lastPollAtMs, now);
  const total = totalElapsedMs(job, now, submittedAtMs);

  return (
    <div
      role="progressbar"
      aria-label="Running query"
      className="sticky top-0 z-40 w-full bg-[var(--color-bg-grey)] border-b border-[var(--color-border)]"
    >
      <div className="h-[6px] w-full flex">
        {STAGES.map((stage, idx) => {
          const render = deriveStageRender(idx, job, now, submittedAtMs);
          const widthPct = (stage.estimatedMs / TOTAL_ESTIMATED_MS) * 100;
          const barColor =
            render.status === "failed"
              ? "var(--color-red)"
              : render.status === "done"
                ? "var(--color-blue-dark)"
                : "var(--color-blue)";
          return (
            <div
              key={stage.key}
              style={{ width: `${widthPct}%` }}
              className="h-full border-r border-white/60 last:border-r-0 bg-[var(--color-bg-grey-2)] relative overflow-hidden"
            >
              <div
                className="absolute inset-y-0 left-0 transition-[width] duration-100 ease-linear"
                style={{
                  width: `${Math.min(100, render.fill * 100)}%`,
                  background: barColor,
                }}
              />
            </div>
          );
        })}
      </div>
      <div className="max-w-[1100px] mx-auto px-4 md:px-8 py-2 flex items-center justify-between gap-4 text-[13px] text-[var(--color-text-secondary)]">
        <div className="flex gap-6">
          {STAGES.map((stage, idx) => {
            const render = deriveStageRender(idx, job, now, submittedAtMs);
            const cls =
              render.status === "running"
                ? "font-bold text-[var(--color-text)]"
                : render.status === "done"
                  ? "text-[var(--color-text-secondary)]"
                  : render.status === "failed"
                    ? "text-[var(--color-red)] font-bold"
                    : "opacity-60";
            return (
              <span key={stage.key} className={cls}>
                {idx + 1}. {stage.label}
              </span>
            );
          })}
        </div>
        <div className="flex items-center gap-4">
          {stale && (
            <span className="italic opacity-70">reconnecting…</span>
          )}
          <span className="tabular-nums font-mono">
            {(total / 1000).toFixed(1)}s
          </span>
        </div>
      </div>
    </div>
  );
}
