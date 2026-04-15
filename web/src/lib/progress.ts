import type { JobResponse, StageName, StageProgress } from "./api";

/**
 * Shared per-stage render derivation used by both QueryProgress (the in-panel
 * card) and StickyProgressBar (the sticky top-of-viewport bar).
 *
 * The rules are the hybrid model from the plan: real progress wins wherever
 * the poll payload has an opinion, synthetic animation fills the gaps so
 * the UI never appears frozen between polls.
 */

export interface StageDef {
  key: StageName;
  label: string;
  description: string;
  estimatedMs: number;
}

export const STAGES: StageDef[] = [
  {
    key: "embed",
    label: "Embed question",
    description: "Titan Text Embeddings v2 over your question",
    estimatedMs: 250,
  },
  {
    key: "retrieve",
    label: "Retrieve schemas",
    description: "Top-K AWS Config schemas from S3 Vectors",
    estimatedMs: 250,
  },
  {
    key: "generate",
    label: "Generate SQL",
    description: "Claude Sonnet writes a single SELECT for Athena",
    estimatedMs: 5500,
  },
  {
    key: "athena",
    label: "Run Athena query",
    description: "Execute the SELECT and fetch the rows",
    estimatedMs: 2500,
  },
];

export const TOTAL_ESTIMATED_MS = STAGES.reduce((a, s) => a + s.estimatedMs, 0);

export type StageRenderStatus = "pending" | "running" | "done" | "failed";

export interface StageRender {
  status: StageRenderStatus;
  fill: number; // 0..1
  realMs?: number;
}

/**
 * Derive per-stage render state for a single stage.
 *
 * Inputs:
 *   idx             - stage index in STAGES
 *   job             - latest poll payload (or null if we haven't polled yet)
 *   now             - current wall-clock ms (Date.now())
 *   submittedAtMs   - ms timestamp when the client fired the submit request
 *
 * Truth sources in priority order:
 *   1. If the job is terminal, every done stage is 100% + its real ms;
 *      the stage that failed (if any) is red.
 *   2. If the poll says the stage is `done`, it's 100% with real ms.
 *   3. If the poll says the stage is `running`, animate from that stage's
 *      server-stamped `started_at` against the estimated duration, capped
 *      at 95% so we never pretend a stage finished without a real signal.
 *   4. If we have no poll yet, animate stage 0 synthetically off the local
 *      submit timestamp (so the sticky bar doesn't freeze before the first
 *      poll lands); everything else stays pending.
 */
export function deriveStageRender(
  idx: number,
  job: JobResponse | null,
  now: number,
  submittedAtMs: number,
): StageRender {
  const def = STAGES[idx];
  const stageState: StageProgress | undefined = job?.stages?.[def.key];

  // Terminal states
  if (job?.status === "succeeded") {
    const ms = stageState?.ms;
    return { status: "done", fill: 1, realMs: ms };
  }
  if (job?.status === "failed") {
    if (stageState?.status === "failed") return { status: "failed", fill: 1, realMs: stageState.ms };
    if (stageState?.status === "done")   return { status: "done", fill: 1, realMs: stageState.ms };
    // The worker died before reaching this stage → stay pending.
    return { status: "pending", fill: 0 };
  }

  // Explicit server-reported states take precedence
  if (stageState?.status === "done") {
    return { status: "done", fill: 1, realMs: stageState.ms };
  }
  if (stageState?.status === "failed") {
    return { status: "failed", fill: 1, realMs: stageState.ms };
  }
  if (stageState?.status === "running" && stageState.started_at) {
    const startedMs = Date.parse(stageState.started_at);
    const elapsed = Math.max(0, now - startedMs);
    const fill = Math.min(0.95, elapsed / def.estimatedMs);
    return { status: "running", fill };
  }

  // No poll yet, or stage not yet seen. Fall back to the synthetic
  // cumulative timeline anchored on the client-side submit moment so
  // the first stage starts animating instantly.
  if (!job) {
    const elapsed = Math.max(0, now - submittedAtMs);
    const stageStart = STAGES.slice(0, idx).reduce((a, s) => a + s.estimatedMs, 0);
    const stageEnd = stageStart + def.estimatedMs;
    const isLast = idx === STAGES.length - 1;
    if (elapsed >= stageEnd) {
      return isLast
        ? { status: "running", fill: 0.95 }
        : { status: "done", fill: 1 };
    }
    if (elapsed >= stageStart) {
      return { status: "running", fill: (elapsed - stageStart) / def.estimatedMs };
    }
    return { status: "pending", fill: 0 };
  }

  // Poll says this stage is pending — honour it.
  return { status: "pending", fill: 0 };
}

/**
 * Is the poll "stale"? Used to drive a subtle reconnecting affordance on
 * the sticky bar. Not an error — just a hint to the user.
 */
export function isPollStale(job: JobResponse | null, lastPollAt: number, now: number): boolean {
  if (!job) return false;
  if (job.status === "succeeded" || job.status === "failed") return false;
  return now - lastPollAt > 3000;
}

/**
 * Total elapsed for the running counter. Prefers wall-clock minus submit
 * (so it matches what the user feels) rather than summing per-stage ms.
 */
export function totalElapsedMs(
  job: JobResponse | null,
  now: number,
  submittedAtMs: number,
): number {
  if (job?.status === "succeeded" && job.result?.timings?.total_ms != null) {
    return job.result.timings.total_ms;
  }
  return Math.max(0, now - submittedAtMs);
}
