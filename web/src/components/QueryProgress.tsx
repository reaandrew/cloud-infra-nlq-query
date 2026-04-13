import { useEffect, useState } from "react";
import { CheckCircle2, AlertCircle } from "lucide-react";
import { cn } from "../lib/cn";
import { fmtMs } from "../lib/format";

/**
 * Stage-by-stage progress display for an in-flight NLQ.
 *
 * Strategy: the API doesn't stream progress, so we fake a believable
 * timeline based on observed median latencies. The component starts at
 * stage 0 and advances through the stages on a timer, never quite
 * filling the last stage. When the response arrives the parent passes
 * `done=true` plus the real timings, and the component snaps to 100%
 * with the real numbers.
 *
 * If the request errors, pass `error=true` and we render a red fail
 * state at whichever stage we got to.
 */

export interface ProgressTimings {
  embed_ms?: number;
  retrieve_ms?: number;
  generate_ms?: number;
  athena_ms?: number;
  total_ms?: number;
}

interface Props {
  running: boolean;
  done: boolean;
  error?: boolean;
  timings?: ProgressTimings;
}

interface StageDef {
  key: keyof ProgressTimings;
  label: string;
  description: string;
  /** Median observed duration in ms, used to drive the synthetic timeline */
  estimatedMs: number;
}

const STAGES: StageDef[] = [
  {
    key: "embed_ms",
    label: "Embed question",
    description: "Titan Text Embeddings v2 over your question",
    estimatedMs: 250,
  },
  {
    key: "retrieve_ms",
    label: "Retrieve schemas",
    description: "Top-K AWS Config schemas from S3 Vectors",
    estimatedMs: 250,
  },
  {
    key: "generate_ms",
    label: "Generate SQL",
    description: "Claude Sonnet writes a single SELECT for Athena",
    estimatedMs: 5500,
  },
  {
    key: "athena_ms",
    label: "Run Athena query",
    description: "Execute the SELECT and fetch the rows",
    estimatedMs: 2500,
  },
];

export function QueryProgress({ running, done, error, timings }: Props) {
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

  return (
    <section aria-label="Query progress" className="space-y-6">
      <div className="flex items-baseline justify-between gap-6 flex-wrap">
        <div>
          <h2 className="gds-m mb-2">
            {error ? "Query failed" : done ? "Query complete" : "Running query"}
          </h2>
          <p className="text-[16px] text-[var(--color-text-secondary)] mb-0">
            {error
              ? "Stopped at the stage shown below."
              : done
                ? "Per-stage timings are shown below."
                : "Typical total is around 8 seconds."}
          </p>
        </div>
        <div className="text-right">
          <div className="text-[14px] font-bold text-[var(--color-text-secondary)]">
            Total
          </div>
          <div className="text-[27px] font-bold tabular-nums text-[var(--color-text)] leading-none mt-1">
            {done && timings?.total_ms ? fmtMs(timings.total_ms) : fmtMs(now)}
          </div>
        </div>
      </div>

      <ol className="divide-y divide-[var(--color-border)] border-t border-[var(--color-border)]">
        {STAGES.map((stage, idx) => (
          <StageRow
            key={stage.key}
            stage={stage}
            index={idx}
            running={running}
            done={done}
            error={error}
            now={now}
            timings={timings}
          />
        ))}
      </ol>
    </section>
  );
}

function StageRow({
  stage,
  index,
  running,
  done,
  error,
  now,
  timings,
}: {
  stage: StageDef;
  index: number;
  running: boolean;
  done: boolean;
  error?: boolean;
  now: number;
  timings?: ProgressTimings;
}) {
  const isLastStage = index === STAGES.length - 1;

  // Compute the "in this stage" range against the synthetic timeline
  const stageStart = STAGES.slice(0, index).reduce((acc, s) => acc + s.estimatedMs, 0);
  const stageEnd = stageStart + stage.estimatedMs;

  let progress = 0;        // 0..1 fill of THIS stage
  let isActive = false;
  let isCompleteSynthetic = false;

  if (running) {
    if (now >= stageEnd) {
      // Synthetic timeline says this stage is "done". But if we're on the
      // LAST stage and the request is still running, leave it in "active"
      // state with an indeterminate fill rather than lying that it finished.
      // Upstream (Bedrock / Athena) can and will run longer than our median
      // estimates.
      if (isLastStage) {
        isActive = true;
        progress = 0.95; // near-full bar, doesn't lie about being done
      } else {
        isCompleteSynthetic = true;
        progress = 1;
      }
    } else if (now >= stageStart) {
      isActive = true;
      progress = (now - stageStart) / stage.estimatedMs;
    }
  }

  // When the request actually finishes, the real timings supersede the
  // synthetic timeline. Each stage shows its real duration.
  const realMs = timings?.[stage.key];
  const showReal = done && realMs !== undefined;

  // Display labels
  const trailing = showReal ? (
    <span className="font-bold">{fmtMs(realMs)}</span>
  ) : isActive ? (
    <span className="text-[var(--color-text-secondary)]">in progress…</span>
  ) : isCompleteSynthetic ? (
    <span className="text-[var(--color-text-secondary)]">{fmtMs(stage.estimatedMs)}</span>
  ) : (
    <span className="text-[var(--color-text-secondary)] opacity-60">queued</span>
  );

  // Visual state
  const errorOnThisStage = error && isActive;
  const stateColor = errorOnThisStage
    ? "var(--color-red)"
    : showReal
      ? "var(--color-green)"
      : isActive
        ? "var(--color-blue)"
        : isCompleteSynthetic
          ? "var(--color-blue-light)"
          : "var(--color-border)";

  return (
    <li className="py-6">
      <div className="flex items-start gap-5">
        <div className="shrink-0 mt-1">
          {errorOnThisStage ? (
            <AlertCircle size={22} className="text-[var(--color-red)]" />
          ) : showReal || isCompleteSynthetic ? (
            <CheckCircle2 size={22} className="text-[var(--color-green)]" />
          ) : (
            <div
              className={cn(
                "size-6 rounded-full border-2 flex items-center justify-center text-[12px] font-bold",
                isActive
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

          {/* progress bar */}
          <div className="mt-4 h-[6px] bg-[var(--color-bg-grey)] overflow-hidden">
            <div
              className="h-full transition-[width] duration-100 ease-linear"
              style={{
                width: `${Math.min(100, Math.max(0, progress * 100))}%`,
                background: stateColor,
              }}
            />
          </div>
        </div>
      </div>
    </li>
  );
}
