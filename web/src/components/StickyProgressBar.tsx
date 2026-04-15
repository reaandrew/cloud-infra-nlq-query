import { useEffect, useState } from "react";
import type { ProgressTimings } from "./QueryProgress";

/**
 * Full-width sticky progress bar that sits under the top nav while a
 * query is running. Four coloured segments, one per stage, each
 * filling over its estimated duration. Disappears when the query
 * finishes or errors.
 */

interface Stage {
  key: keyof ProgressTimings;
  label: string;
  estimatedMs: number;
}

const STAGES: Stage[] = [
  { key: "embed_ms", label: "Embed", estimatedMs: 250 },
  { key: "retrieve_ms", label: "Retrieve", estimatedMs: 250 },
  { key: "generate_ms", label: "Generate SQL", estimatedMs: 5500 },
  { key: "athena_ms", label: "Athena", estimatedMs: 2500 },
];

const TOTAL_ESTIMATED = STAGES.reduce((a, s) => a + s.estimatedMs, 0);

interface Props {
  running: boolean;
}

export function StickyProgressBar({ running }: Props) {
  const [now, setNow] = useState(0);

  useEffect(() => {
    if (!running) return;
    setNow(0);
    const start = performance.now();
    const id = window.setInterval(() => {
      setNow(performance.now() - start);
    }, 50);
    return () => window.clearInterval(id);
  }, [running]);

  if (!running) return null;

  return (
    <div
      role="progressbar"
      aria-label="Running query"
      className="sticky top-0 z-40 w-full bg-[var(--color-bg-grey)] border-b border-[var(--color-border)]"
    >
      <div className="h-[6px] w-full flex">
        {STAGES.map((stage, idx) => {
          const stageStart = STAGES.slice(0, idx).reduce((a, s) => a + s.estimatedMs, 0);
          const stageEnd = stageStart + stage.estimatedMs;
          const isLast = idx === STAGES.length - 1;

          let fill = 0;
          if (now >= stageEnd) {
            fill = isLast ? 0.95 : 1;
          } else if (now >= stageStart) {
            fill = (now - stageStart) / stage.estimatedMs;
          }
          const widthPct = (stage.estimatedMs / TOTAL_ESTIMATED) * 100;

          return (
            <div
              key={stage.key}
              style={{ width: `${widthPct}%` }}
              className="h-full border-r border-white/60 last:border-r-0 bg-[var(--color-bg-grey-2)] relative overflow-hidden"
            >
              <div
                className="absolute inset-y-0 left-0 bg-[var(--color-blue)] transition-[width] duration-100 ease-linear"
                style={{ width: `${Math.min(100, fill * 100)}%` }}
              />
            </div>
          );
        })}
      </div>
      <div className="max-w-[1100px] mx-auto px-4 md:px-8 py-2 flex items-center justify-between gap-4 text-[13px] text-[var(--color-text-secondary)]">
        <div className="flex gap-6">
          {STAGES.map((stage, idx) => {
            const stageStart = STAGES.slice(0, idx).reduce((a, s) => a + s.estimatedMs, 0);
            const stageEnd = stageStart + stage.estimatedMs;
            const isActive = now >= stageStart && now < stageEnd;
            const done = now >= stageEnd && idx < STAGES.length - 1;
            return (
              <span
                key={stage.key}
                className={
                  isActive
                    ? "font-bold text-[var(--color-text)]"
                    : done
                      ? "text-[var(--color-text-secondary)]"
                      : "opacity-60"
                }
              >
                {idx + 1}. {stage.label}
              </span>
            );
          })}
        </div>
        <span className="tabular-nums font-mono">
          {(now / 1000).toFixed(1)}s
        </span>
      </div>
    </div>
  );
}
