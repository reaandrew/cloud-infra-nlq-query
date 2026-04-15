import { useEffect, useState } from "react";
import { CheckCircle2, AlertCircle } from "lucide-react";
import { cn } from "../lib/cn";
import { fmtMs } from "../lib/format";
import type { JobResponse } from "../lib/api";
import {
  STAGES,
  deriveStageRender,
  totalElapsedMs,
  type StageDef,
  type StageRender,
} from "../lib/progress";

/**
 * Stage-by-stage progress display for an in-flight NLQ.
 *
 * Hybrid of real and synthetic:
 *  - If we have a `job` from polling, that's the source of truth — per-stage
 *    status comes from the poll, with the running stage's fill animated
 *    locally between polls so the bars never freeze.
 *  - If `job` is null (submit-in-flight, or first poll hasn't landed yet),
 *    fall back to a purely synthetic timeline anchored on `submittedAtMs`
 *    so the UI starts moving the moment the user clicks.
 */

interface Props {
  running: boolean;
  job: JobResponse | null;
  submittedAtMs: number;
  error?: boolean;
}

export function QueryProgress({ running, job, submittedAtMs, error }: Props) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!running && job?.status !== "succeeded" && job?.status !== "failed") {
      return;
    }
    // Keep ticking while running so the synthetic interpolation keeps
    // flowing between polls.
    if (!running) {
      setNow(Date.now());
      return;
    }
    const id = window.setInterval(() => setNow(Date.now()), 50);
    return () => window.clearInterval(id);
  }, [running, job?.status]);

  const headingText =
    error || job?.status === "failed"
      ? "Query failed"
      : job?.status === "succeeded"
        ? "Query complete"
        : "Running query";
  const subText =
    error || job?.status === "failed"
      ? "Stopped at the stage shown below."
      : job?.status === "succeeded"
        ? "Per-stage timings are shown below."
        : "Typical total is around 8 seconds.";

  const total = totalElapsedMs(job, now, submittedAtMs);

  return (
    <section aria-label="Query progress" className="space-y-6">
      <div className="flex items-baseline justify-between gap-6 flex-wrap">
        <div>
          <h2 className="gds-m mb-2">{headingText}</h2>
          <p className="text-[16px] text-[var(--color-text-secondary)] mb-0">
            {subText}
          </p>
        </div>
        <div className="text-right">
          <div className="text-[14px] font-bold text-[var(--color-text-secondary)]">
            Total
          </div>
          <div className="text-[27px] font-bold tabular-nums text-[var(--color-text)] leading-none mt-1">
            {fmtMs(total)}
          </div>
        </div>
      </div>

      <ol className="divide-y divide-[var(--color-border)] border-t border-[var(--color-border)]">
        {STAGES.map((stage, idx) => (
          <StageRow
            key={stage.key}
            stage={stage}
            render={deriveStageRender(idx, job, now, submittedAtMs)}
            index={idx}
          />
        ))}
      </ol>
    </section>
  );
}

function StageRow({
  stage,
  render,
  index,
}: {
  stage: StageDef;
  render: StageRender;
  index: number;
}) {
  const isFailed = render.status === "failed";
  const isDone = render.status === "done";
  const isRunning = render.status === "running";

  const trailing = render.realMs != null ? (
    <span className="font-bold">{fmtMs(render.realMs)}</span>
  ) : isRunning ? (
    <span className="text-[var(--color-text-secondary)]">in progress…</span>
  ) : isDone ? (
    <span className="text-[var(--color-text-secondary)]">{fmtMs(stage.estimatedMs)}</span>
  ) : (
    <span className="text-[var(--color-text-secondary)] opacity-60">queued</span>
  );

  const stateColor = isFailed
    ? "var(--color-red)"
    : isDone
      ? "var(--color-green)"
      : isRunning
        ? "var(--color-blue)"
        : "var(--color-border)";

  return (
    <li className="py-6">
      <div className="flex items-start gap-5">
        <div className="shrink-0 mt-1">
          {isFailed ? (
            <AlertCircle size={22} className="text-[var(--color-red)]" />
          ) : isDone ? (
            <CheckCircle2 size={22} className="text-[var(--color-green)]" />
          ) : (
            <div
              className={cn(
                "size-6 rounded-full border-2 flex items-center justify-center text-[12px] font-bold",
                isRunning
                  ? "border-[var(--color-blue)] text-[var(--color-blue)] animate-pulse-soft"
                  : "border-[var(--color-border)] text-[var(--color-text-secondary)]",
              )}
            >
              {index + 1}
            </div>
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline justify-between gap-4">
            <div className="text-[19px] font-bold text-[var(--color-text)]">
              {stage.label}
            </div>
            <div className="text-[16px] tabular-nums text-[var(--color-text)]">
              {trailing}
            </div>
          </div>
          <div className="text-[15px] text-[var(--color-text-secondary)] mt-1">
            {stage.description}
          </div>

          <div className="mt-4 h-[6px] bg-[var(--color-bg-grey)] overflow-hidden">
            <div
              className="h-full transition-[width] duration-100 ease-linear"
              style={{
                width: `${Math.min(100, Math.max(0, render.fill * 100))}%`,
                background: stateColor,
              }}
            />
          </div>
        </div>
      </div>
    </li>
  );
}

