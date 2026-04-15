import { useState, useMemo, useRef, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertCircle, ChevronRight, Lock } from "lucide-react";
import {
  api,
  ApiError,
  type JobResponse,
  type NlqResponse,
  type NlqResult,
  type RetrievedSchema,
} from "../lib/api";
import { Button } from "../components/ui/Button";
import { Badge } from "../components/ui/Badge";
import { QueryProgress } from "../components/QueryProgress";
import { StickyProgressBar } from "../components/StickyProgressBar";
import { fmtNumber } from "../lib/format";
import { EXAMPLE_CATEGORIES, EXAMPLES, type Example } from "../data/examples";
import { cn } from "../lib/cn";

interface QueryViewProps {
  hasApiKey: boolean;
  onRequireApiKey: () => void;
}

export function QueryView({ hasApiKey, onRequireApiKey }: QueryViewProps) {
  const [question, setQuestion] = useState("");
  const [activeCategory, setActiveCategory] = useState<string>(EXAMPLE_CATEGORIES[0].id);
  const [jobId, setJobId] = useState<string | null>(null);
  const submittedAtRef = useRef<number>(0);
  const lastPollAtRef = useRef<number>(0);

  const submit = useMutation<{ job_id: string; status_url: string }, ApiError, string>({
    mutationFn: (q: string) => api.submitJob({ question: q }),
    onMutate: () => {
      submittedAtRef.current = Date.now();
      lastPollAtRef.current = Date.now();
      setJobId(null);
    },
    onSuccess: (res) => {
      setJobId(res.job_id);
    },
  });

  const job = useQuery<JobResponse, ApiError>({
    queryKey: ["job", jobId],
    queryFn: async () => {
      const res = await api.getJob(jobId!);
      lastPollAtRef.current = Date.now();
      return res;
    },
    enabled: !!jobId,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      if (s === "succeeded" || s === "failed") return false;
      return 800;
    },
    staleTime: 0,
    gcTime: 5 * 60 * 1000,
    retry: 2,
  });

  // Unified query state
  const jobData: JobResponse | null = job.data ?? null;
  const isRunning =
    submit.isPending ||
    (!!jobId && (jobData?.status === "queued" || jobData?.status === "running" || !jobData));
  const isDone = jobData?.status === "succeeded";
  const hasError = submit.isError || jobData?.status === "failed";
  const result: NlqResult | null = jobData?.status === "succeeded" ? jobData.result ?? null : null;

  const submitError: ApiError | null = submit.error ?? null;
  const jobError = jobData?.status === "failed" ? jobData.error ?? null : null;

  const fireQuestion = (q: string) => {
    submit.mutate(q);
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const q = question.trim();
    if (!q) return;
    if (!hasApiKey) {
      onRequireApiKey();
      return;
    }
    fireQuestion(q);
  };

  const onPickExample = (ex: Example) => {
    if (isRunning) return; // block clicks while a query is in flight
    setQuestion(ex.question);
    if (!hasApiKey) {
      onRequireApiKey();
      return;
    }
    fireQuestion(ex.question);
  };

  const examplesForCategory = useMemo(
    () => EXAMPLES.filter((e) => e.category === activeCategory),
    [activeCategory],
  );

  return (
    <>
      <StickyProgressBar
        running={isRunning}
        job={jobData}
        submittedAtMs={submittedAtRef.current}
        lastPollAtMs={lastPollAtRef.current}
      />
      <div className="max-w-[1100px] mx-auto px-4 md:px-8 py-16 space-y-16">
      {/* ---- heading ---- */}
      <div>
        <h1 className="gds-l mb-4">Ask a question</h1>
        <p className="text-[19px] leading-[1.47] text-[var(--color-text-secondary)] mb-0">
          Describe what you want to know in plain English. The retriever finds
          the most relevant AWS Config resource schemas from the vector index,
          a large language model writes a single Athena <code>SELECT</code>{" "}
          using those schemas as context, and the query runs against the
          Iceberg table.
        </p>
      </div>

      {/* ---- form ---- */}
      <form onSubmit={onSubmit} className="space-y-4">
        <label htmlFor="nlq-input" className="block text-[19px] font-bold">
          Your question
        </label>
        <textarea
          id="nlq-input"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="for each EC2 instance show its attached volumes joining EC2::Instance with EC2::Volume"
          rows={3}
          className={cn(
            "w-full resize-none px-3 py-3 text-[19px] text-[var(--color-text)]",
            "bg-white border-2 border-[var(--color-text)] focus:outline-none",
            "placeholder:text-[var(--color-text-secondary)]",
          )}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
              e.preventDefault();
              onSubmit(e as unknown as FormEvent);
            }
          }}
        />
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-4 text-[16px] text-[var(--color-text-secondary)]">
            <span>
              Press{" "}
              <kbd className="px-1.5 py-0.5 border border-[var(--color-border)] bg-[var(--color-bg-grey)] text-[14px] font-mono">
                ⌘
              </kbd>{" "}
              +{" "}
              <kbd className="px-1.5 py-0.5 border border-[var(--color-border)] bg-[var(--color-bg-grey)] text-[14px] font-mono">
                Enter
              </kbd>{" "}
              to run
            </span>
            {!hasApiKey && (
              <span className="flex items-center gap-1 text-[var(--color-orange)] font-bold">
                <Lock size={14} />
                API key required
              </span>
            )}
          </div>
          <Button type="submit" disabled={!question.trim() || isRunning}>
            {isRunning ? "Running…" : "Ask the question"}
          </Button>
        </div>
      </form>

      {/* ---- progress ---- */}
      {(isRunning || isDone || hasError) && (
        <QueryProgress
          running={isRunning}
          job={jobData}
          submittedAtMs={submittedAtRef.current}
          error={hasError}
        />
      )}

      {/* ---- error ---- */}
      {submitError && <ErrorBanner error={submitError} />}
      {jobError && <JobErrorBanner error={jobError} />}

      {/* ---- result ---- */}
      {isDone && result && <ResultPanel data={result} />}

      {/* ---- examples (quick-start, grouped by complexity level) ----
       * Always rendered. Picking another example after a result kicks off a
       * new mutation, which clears the previous result via the pending state.
       */}
      <section aria-labelledby="examples-heading" className="space-y-8">
        <div>
          <h2 id="examples-heading" className="gds-m mb-3">
            Quick start
          </h2>
          <p className="text-[19px] leading-[1.47] text-[var(--color-text-secondary)] mb-0">
            Click one of the example questions below to see the system in
            action. The tabs are ordered by increasing complexity, from a
            simple row count up to a four-way resource join, so you can get
            a feel for how far the natural-language engine goes.
          </p>
        </div>

        <div className="border-b border-[var(--color-border)]">
          <ul className="flex items-end gap-0 -mb-px flex-wrap" role="tablist">
            {EXAMPLE_CATEGORIES.map((c) => (
              <li key={c.id}>
                <button
                  role="tab"
                  aria-selected={activeCategory === c.id}
                  disabled={isRunning}
                  onClick={() => setActiveCategory(c.id)}
                  className={cn(
                    "px-6 py-4 text-[19px] font-bold relative flex items-center gap-3",
                    isRunning && "opacity-50",
                    activeCategory === c.id
                      ? "text-[var(--color-text)]"
                      : "text-[var(--color-link)] hover:text-[var(--color-link-hover)]",
                  )}
                >
                  <span
                    className={cn(
                      "inline-flex items-center justify-center size-7 text-[14px] font-bold",
                      activeCategory === c.id
                        ? "bg-[var(--color-blue)] text-white"
                        : "bg-[var(--color-bg-grey)] text-[var(--color-text-secondary)]",
                    )}
                    aria-hidden
                  >
                    {c.level}
                  </span>
                  <span>{c.title}</span>
                  {activeCategory === c.id && (
                    <span
                      className="absolute inset-x-0 bottom-0 h-[4px] bg-[var(--color-blue)]"
                      aria-hidden
                    />
                  )}
                </button>
              </li>
            ))}
          </ul>
        </div>

        {/* ---- active level description ---- */}
        {(() => {
          const cat = EXAMPLE_CATEGORIES.find((c) => c.id === activeCategory);
          if (!cat) return null;
          return (
            <p className="text-[16px] leading-[1.5] text-[var(--color-text-secondary)] mb-0">
              {cat.description}
            </p>
          );
        })()}

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-x-10 gap-y-12 pt-2">
          {examplesForCategory.map((ex) => (
            <ExampleItem
              key={ex.id}
              example={ex}
              onClick={() => onPickExample(ex)}
              disabled={isRunning}
            />
          ))}
        </div>
      </section>
      </div>
    </>
  );
}

// ---------- example item (flat, no card) ----------

function ExampleItem({
  example,
  onClick,
  disabled,
}: {
  example: Example;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-disabled={disabled}
      className={cn(
        "text-left block group",
        disabled && "opacity-50",
      )}
    >
      <div className="flex items-start gap-2">
        <div
          className={cn(
            "text-[19px] font-bold underline",
            disabled
              ? "text-[var(--color-text-secondary)] no-underline"
              : "text-[var(--color-link)] group-hover:text-[var(--color-link-hover)] group-hover:decoration-[3px]",
          )}
        >
          {example.title}
        </div>
        <ChevronRight
          size={18}
          className={cn(
            "shrink-0 mt-1",
            disabled
              ? "text-[var(--color-text-secondary)]"
              : "text-[var(--color-link)] group-hover:text-[var(--color-link-hover)]",
          )}
        />
      </div>
      <p className="mt-1 text-[15px] text-[var(--color-text-secondary)]">
        {example.description}
      </p>
      <p className="mt-2 text-[14px] text-[var(--color-text)] italic">
        “{example.question}”
      </p>
    </button>
  );
}

// ---------- error banner ----------

function ErrorBanner({ error }: { error: ApiError }) {
  return (
    <div className="border-l-[10px] border-[var(--color-red)] bg-[var(--color-red-bg)] p-5">
      <div className="flex items-start gap-3">
        <AlertCircle size={22} className="text-[var(--color-red)] shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <h2 className="text-[24px] font-bold text-[var(--color-red)]">
            {error.body?.error || error.message}
          </h2>
          {error.body?.detail && (
            <p className="mt-1 text-[16px] text-[var(--color-text)]">
              {error.body.detail}
            </p>
          )}
          {error.body?.sql && (
            <pre className="mt-3 text-[13px] font-mono bg-white border border-[var(--color-border)] p-3 overflow-x-auto">
              {error.body.sql}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------- job-failed banner ----------

function JobErrorBanner({
  error,
}: {
  error: NonNullable<JobResponse["error"]>;
}) {
  return (
    <div className="border-l-[10px] border-[var(--color-red)] bg-[var(--color-red-bg)] p-5">
      <div className="flex items-start gap-3">
        <AlertCircle size={22} className="text-[var(--color-red)] shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <h2 className="text-[24px] font-bold text-[var(--color-red)]">
            {error.error || "Query failed"}
          </h2>
          {error.stage && (
            <p className="mt-1 text-[14px] uppercase tracking-wider text-[var(--color-text-secondary)] font-bold">
              Failed at stage: {error.stage}
            </p>
          )}
          {error.detail && (
            <p className="mt-1 text-[16px] text-[var(--color-text)]">
              {error.detail}
            </p>
          )}
          {error.sql && (
            <pre className="mt-3 text-[13px] font-mono bg-white border border-[var(--color-border)] p-3 overflow-x-auto">
              {error.sql}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------- result metadata strip ----------

function fmtBytes(n?: number | null): string | null {
  if (n == null) return null;
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function ResultMeta({ data }: { data: NlqResponse }) {
  const stats = data.athena_stats;
  const items: { label: string; value: string }[] = [
    {
      label: "Rows returned",
      value: data.row_count ? fmtNumber(data.row_count) : "0",
    },
  ];
  if (stats?.data_scanned_bytes != null) {
    items.push({
      label: "Data scanned",
      value: fmtBytes(stats.data_scanned_bytes) ?? "—",
    });
  }
  if (stats?.engine_execution_ms != null) {
    items.push({
      label: "Engine time",
      value: `${(stats.engine_execution_ms / 1000).toFixed(2)} s`,
    });
  }
  if (stats?.query_planning_ms != null) {
    items.push({
      label: "Planning",
      value: `${stats.query_planning_ms} ms`,
    });
  }
  if (stats?.query_queue_ms != null) {
    items.push({
      label: "Queue",
      value: `${stats.query_queue_ms} ms`,
    });
  }
  return (
    <dl className="flex flex-wrap gap-x-10 gap-y-3 mt-0">
      {items.map((it) => (
        <div key={it.label} className="flex flex-col">
          <dt className="text-[13px] uppercase tracking-wider font-bold text-[var(--color-text-secondary)]">
            {it.label}
          </dt>
          <dd className="text-[19px] font-bold tabular-nums text-[var(--color-text)] mt-0.5">
            {it.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

// ---------- result panel ----------

function ResultPanel({ data }: { data: NlqResponse }) {
  const headers = data.columns?.length
    ? data.columns
    : data.rows[0]
      ? Object.keys(data.rows[0])
      : [];

  return (
    <div className="space-y-16 animate-fade-in">
      {/* ---- generated SQL ---- */}
      <section aria-labelledby="sql-heading">
        <h2 id="sql-heading" className="gds-m mb-2">
          Generated SQL
        </h2>
        <p className="text-[16px] text-[var(--color-text-secondary)] mb-4">
          Validated SELECT-only before execution.
        </p>
        <pre className="px-6 py-5 text-[14px] leading-[1.55] font-mono text-[var(--color-text)] overflow-x-auto whitespace-pre bg-[var(--color-bg-grey)] border-l-[5px] border-[var(--color-blue)]">
          {data.sql}
        </pre>
      </section>

      {/* ---- retrieved schemas ---- */}
      <section aria-labelledby="schemas-heading">
        <div className="flex items-baseline justify-between gap-4 mb-2 flex-wrap">
          <h2 id="schemas-heading" className="gds-m mb-0">
            Retrieved schemas
          </h2>
          <Badge tone="blue">{data.retrieved_schemas.length} top matches</Badge>
        </div>
        <p className="text-[16px] text-[var(--color-text-secondary)] mb-6">
          The closest matches from the S3 Vectors index, in order.
        </p>
        <ul className="divide-y divide-[var(--color-border)]">
          {data.retrieved_schemas.map((s: RetrievedSchema, i: number) => (
            <li key={i} className="flex items-center gap-5 py-4">
              <span className="size-8 bg-[var(--color-blue)] text-white text-[14px] font-bold flex items-center justify-center shrink-0">
                {i + 1}
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-[17px] font-mono text-[var(--color-text)] truncate font-bold">
                  {s.resource_type}
                </div>
                <div className="text-[14px] text-[var(--color-text-secondary)] flex gap-3 mt-1">
                  {s.service && <span>{s.service}</span>}
                  {s.category && <span>· {s.category}</span>}
                  {s.field_count && <span>· {s.field_count} fields</span>}
                </div>
              </div>
              <div className="text-[14px] text-[var(--color-text-secondary)] font-mono tabular-nums">
                d {s.distance.toFixed(3)}
              </div>
            </li>
          ))}
        </ul>
      </section>

      {/* ---- results table ---- */}
      <section aria-labelledby="results-heading">
        <h2 id="results-heading" className="gds-m mb-2">
          Results
        </h2>
        <ResultMeta data={data} />
        <div className="mb-6" />
        <div className="overflow-x-auto">
          {!headers.length ? (
            <p className="text-[16px] text-[var(--color-text-secondary)]">
              No rows returned.
            </p>
          ) : (
            <table className="w-full text-[15px]">
              <thead>
                <tr>
                  {headers.map((h) => (
                    <th
                      key={h}
                      className="text-left font-bold px-4 py-3 whitespace-nowrap border-b border-[var(--color-border)] text-[14px] uppercase tracking-wide text-[var(--color-text-secondary)]"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r, i) => (
                  <tr
                    key={i}
                    className="border-b border-[var(--color-border)]"
                  >
                    {headers.map((h) => (
                      <td
                        key={h}
                        className="px-4 py-3 text-[14px] text-[var(--color-text)] whitespace-nowrap font-mono"
                      >
                        {r[h] ?? ""}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>
    </div>
  );
}
