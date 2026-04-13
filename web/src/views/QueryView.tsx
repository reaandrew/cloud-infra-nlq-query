import { useState, useMemo, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  Sparkles,
  ArrowRight,
  Loader2,
  AlertCircle,
  ChevronRight,
  Database,
  Code2,
  ListChecks,
  Layers3,
  Clock,
  CheckCircle2,
  Lock,
} from "lucide-react";
import { api, ApiError, type NlqResponse, type RetrievedSchema } from "../lib/api";
import { Card, CardHeader, CardBody } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { Badge } from "../components/ui/Badge";
import { Skeleton } from "../components/ui/Skeleton";
import { fmtMs, fmtNumber } from "../lib/format";
import { EXAMPLE_CATEGORIES, EXAMPLES, type Example } from "../data/examples";
import { cn } from "../lib/cn";

interface QueryViewProps {
  hasApiKey: boolean;
  onRequireApiKey: () => void;
}

export function QueryView({ hasApiKey, onRequireApiKey }: QueryViewProps) {
  const [question, setQuestion] = useState("");
  const [activeCategory, setActiveCategory] = useState<string>(EXAMPLE_CATEGORIES[0].id);

  const ask = useMutation<NlqResponse, ApiError, void>({
    mutationFn: () => api.ask({ question: question.trim() }),
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    if (!hasApiKey) {
      onRequireApiKey();
      return;
    }
    ask.mutate();
  };

  const onPickExample = (ex: Example) => {
    setQuestion(ex.question);
    if (!hasApiKey) {
      onRequireApiKey();
      return;
    }
    // Fire immediately so the user gets instant feedback
    setTimeout(() => {
      ask.mutate();
    }, 0);
  };

  const examplesForCategory = useMemo(
    () => EXAMPLES.filter((e) => e.category === activeCategory),
    [activeCategory],
  );

  return (
    <div className="px-10 py-8 max-w-[1400px] mx-auto space-y-8">
      {/* ---- header + input ---- */}
      <div>
        <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-[var(--color-fg-muted)] font-semibold">
          <Sparkles size={12} className="text-[var(--color-accent-500)]" />
          Natural language → SQL
        </div>
        <h1 className="mt-1 text-3xl font-bold tracking-tight text-[var(--color-fg-primary)]">
          Ask the estate
        </h1>
        <p className="mt-1 text-sm text-[var(--color-fg-muted)] max-w-2xl">
          Describe what you want to know in plain English. The retriever finds the
          most relevant AWS Config resource schemas, Claude generates an Athena
          SELECT, the SELECT runs against your Iceberg table, and you get rows
          back.
        </p>
      </div>

      <Card className="overflow-visible">
        <CardBody className="p-5">
          <form onSubmit={onSubmit} className="flex flex-col gap-3">
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="e.g. for each EC2 instance show its attached volumes joining EC2::Instance with EC2::Volume"
              rows={3}
              className={cn(
                "w-full resize-none px-4 py-3 text-[15px] text-[var(--color-fg-primary)] placeholder:text-[var(--color-fg-muted)]",
                "rounded-lg border border-[var(--color-border-subtle)] focus:border-[var(--color-accent-500)]",
                "focus:outline-none focus:ring-2 focus:ring-[var(--color-accent-500)]/20",
                "transition",
              )}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                  e.preventDefault();
                  onSubmit(e as unknown as FormEvent);
                }
              }}
            />
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3 text-xs text-[var(--color-fg-muted)]">
                <kbd className="px-1.5 py-0.5 rounded border border-[var(--color-border-default)] bg-white text-[10px] font-mono">⌘↵</kbd>
                to run
                {!hasApiKey && (
                  <span className="flex items-center gap-1 text-[var(--color-warning-700)]">
                    <Lock size={12} />
                    API key required
                  </span>
                )}
              </div>
              <Button type="submit" disabled={!question.trim() || ask.isPending}>
                {ask.isPending ? (
                  <>
                    <Loader2 size={14} className="animate-spin" />
                    Running…
                  </>
                ) : (
                  <>
                    Ask
                    <ArrowRight size={14} />
                  </>
                )}
              </Button>
            </div>
          </form>
        </CardBody>
      </Card>

      {/* ---- results panel ---- */}
      {ask.isPending && <RunningCard />}
      {ask.error && <ErrorCard error={ask.error} />}
      {ask.data && <ResultPanel data={ask.data} />}

      {/* ---- examples ---- */}
      {!ask.data && !ask.isPending && (
        <div className="space-y-4">
          <div>
            <h2 className="text-base font-semibold tracking-tight text-[var(--color-fg-primary)]">
              Pick a starting point
            </h2>
            <p className="text-sm text-[var(--color-fg-muted)]">
              Curated example queries grouped by what they show off. Click one to run.
            </p>
          </div>

          <div className="flex items-center gap-1.5 border-b border-[var(--color-border-subtle)]">
            {EXAMPLE_CATEGORIES.map((c) => (
              <button
                key={c.id}
                onClick={() => setActiveCategory(c.id)}
                className={cn(
                  "px-4 py-2.5 text-sm font-medium transition relative",
                  activeCategory === c.id
                    ? "text-[var(--color-accent-700)]"
                    : "text-[var(--color-fg-muted)] hover:text-[var(--color-fg-primary)]",
                )}
              >
                {c.title}
                {activeCategory === c.id && (
                  <span className="absolute inset-x-3 -bottom-px h-0.5 bg-[var(--color-accent-600)] rounded-full" />
                )}
              </button>
            ))}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {examplesForCategory.map((ex) => (
              <ExampleCard key={ex.id} example={ex} onClick={() => onPickExample(ex)} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------- example card ----------

function ExampleCard({ example, onClick }: { example: Example; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "text-left bg-white border border-[var(--color-border-subtle)] rounded-xl p-5",
        "hover:border-[var(--color-accent-200)] hover:shadow-[var(--shadow-elevated)] transition",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent-500)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--color-bg-app)]",
        "group",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="font-semibold text-sm text-[var(--color-fg-primary)] tracking-tight">
          {example.title}
        </div>
        <ChevronRight
          size={16}
          className="shrink-0 text-[var(--color-fg-muted)] group-hover:text-[var(--color-accent-600)] transition-colors mt-0.5"
        />
      </div>
      <p className="mt-2 text-xs text-[var(--color-fg-muted)] leading-relaxed">
        {example.description}
      </p>
      <div className="mt-3 pt-3 border-t border-[var(--color-border-subtle)]">
        <div className="text-[11px] uppercase tracking-wider font-semibold text-[var(--color-fg-muted)] mb-1">
          Question
        </div>
        <div className="text-xs text-[var(--color-fg-secondary)] line-clamp-2 leading-snug">
          {example.question}
        </div>
      </div>
    </button>
  );
}

// ---------- running placeholder ----------

function RunningCard() {
  return (
    <Card>
      <CardBody className="flex items-center gap-4 py-8">
        <Loader2 size={20} className="text-[var(--color-accent-600)] animate-spin shrink-0" />
        <div className="space-y-1.5 flex-1">
          <div className="text-sm font-medium text-[var(--color-fg-primary)]">
            Running query
          </div>
          <div className="text-xs text-[var(--color-fg-muted)]">
            Embed → retrieve → generate SQL → execute against Athena. Typically 5–10 s.
          </div>
        </div>
      </CardBody>
    </Card>
  );
}

// ---------- error card ----------

function ErrorCard({ error }: { error: ApiError }) {
  return (
    <Card className="border-[var(--color-danger-500)]/30">
      <CardBody>
        <div className="flex items-start gap-3">
          <AlertCircle size={18} className="text-[var(--color-danger-500)] shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <div className="text-sm font-semibold text-[var(--color-danger-700)]">
              {error.body?.error || error.message}
            </div>
            {error.body?.detail && (
              <div className="mt-1 text-xs text-[var(--color-fg-secondary)]">
                {error.body.detail}
              </div>
            )}
            {error.body?.sql && (
              <pre className="mt-3 text-[11px] font-mono bg-[var(--color-bg-app)] border border-[var(--color-border-subtle)] rounded-md p-3 overflow-x-auto">
                {error.body.sql}
              </pre>
            )}
          </div>
        </div>
      </CardBody>
    </Card>
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
    <div className="space-y-6 animate-fade-in">
      {/* ---- summary strip ---- */}
      <Card>
        <CardBody className="flex flex-wrap items-center gap-x-8 gap-y-3 py-4">
          <Stat
            icon={<CheckCircle2 size={14} className="text-[var(--color-success-500)]" />}
            label="Rows"
            value={fmtNumber(data.row_count)}
          />
          <Stat
            icon={<Clock size={14} className="text-[var(--color-fg-muted)]" />}
            label="Total"
            value={fmtMs(data.timings.total_ms)}
          />
          <Stat
            icon={<Sparkles size={14} className="text-[var(--color-accent-500)]" />}
            label="Generate"
            value={fmtMs(data.timings.generate_ms)}
          />
          <Stat
            icon={<Database size={14} className="text-[var(--color-fg-muted)]" />}
            label="Athena"
            value={fmtMs(data.timings.athena_ms)}
          />
          <Stat
            icon={<Layers3 size={14} className="text-[var(--color-fg-muted)]" />}
            label="Embed + retrieve"
            value={fmtMs((data.timings.embed_ms ?? 0) + (data.timings.retrieve_ms ?? 0))}
          />
          {data.athena_query_id && (
            <div className="ml-auto text-[11px] font-mono text-[var(--color-fg-muted)] truncate max-w-xs">
              {data.athena_query_id}
            </div>
          )}
        </CardBody>
      </Card>

      {/* ---- generated SQL ---- */}
      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              <Code2 size={14} className="text-[var(--color-accent-600)]" />
              Generated SQL
            </span>
          }
          subtitle="Validated SELECT-only before execution"
        />
        <CardBody className="p-0">
          <pre className="px-6 py-5 text-[12px] leading-[1.55] font-mono text-[var(--color-fg-primary)] overflow-x-auto whitespace-pre">
            {data.sql}
          </pre>
        </CardBody>
      </Card>

      {/* ---- retrieved schemas ---- */}
      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              <Layers3 size={14} className="text-[var(--color-accent-600)]" />
              Retrieved schemas
            </span>
          }
          subtitle="Top matches from the S3 Vectors index"
          actions={<Badge tone="accent">{data.retrieved_schemas.length}</Badge>}
        />
        <CardBody className="p-0">
          <ul className="divide-y divide-[var(--color-border-subtle)]">
            {data.retrieved_schemas.map((s: RetrievedSchema, i: number) => (
              <li key={i} className="px-6 py-3 flex items-center gap-4">
                <span className="size-6 rounded-md bg-[var(--color-accent-50)] text-[var(--color-accent-700)] text-[11px] font-bold flex items-center justify-center shrink-0">
                  {i + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-mono text-[var(--color-fg-primary)] truncate">
                    {s.resource_type}
                  </div>
                  <div className="text-[11px] text-[var(--color-fg-muted)] flex gap-3 mt-0.5">
                    {s.service && <span>{s.service}</span>}
                    {s.category && <span>·  {s.category}</span>}
                    {s.field_count && <span>·  {s.field_count} fields</span>}
                  </div>
                </div>
                <Badge tone="neutral">d {s.distance.toFixed(3)}</Badge>
              </li>
            ))}
          </ul>
        </CardBody>
      </Card>

      {/* ---- result rows table ---- */}
      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              <ListChecks size={14} className="text-[var(--color-accent-600)]" />
              Results
            </span>
          }
          subtitle={data.row_count ? `${fmtNumber(data.row_count)} rows` : "empty"}
        />
        <div className="overflow-x-auto">
          {!headers.length ? (
            <div className="px-6 py-8 text-sm text-[var(--color-fg-muted)]">
              No rows returned.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-[var(--color-bg-app)] text-xs uppercase tracking-wider text-[var(--color-fg-muted)]">
                <tr>
                  {headers.map((h) => (
                    <th key={h} className="text-left font-semibold px-6 py-3 whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r, i) => (
                  <tr
                    key={i}
                    className="border-t border-[var(--color-border-subtle)] hover:bg-[var(--color-accent-50)]/50"
                  >
                    {headers.map((h) => (
                      <td
                        key={h}
                        className="px-6 py-2.5 text-[13px] text-[var(--color-fg-primary)] whitespace-nowrap font-mono"
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
      </Card>
    </div>
  );
}

function Stat({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="shrink-0">{icon}</span>
      <div>
        <div className="text-[10px] uppercase tracking-wider font-semibold text-[var(--color-fg-muted)] leading-none">
          {label}
        </div>
        <div className="mt-1 text-sm font-semibold tabular-nums text-[var(--color-fg-primary)] leading-none">
          {value}
        </div>
      </div>
    </div>
  );
}

// suppress unused-symbol warning for Skeleton import we keep around for future use
void Skeleton;
