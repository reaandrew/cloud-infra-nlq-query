import { useQuery } from "@tanstack/react-query";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
} from "recharts";
import {
  Boxes,
  Building2,
  Layers3,
  Globe2,
  Activity,
  RefreshCcw,
  AlertCircle,
} from "lucide-react";
import { api, type AccountCount } from "../lib/api";
import { Card, CardHeader, CardBody } from "../components/ui/Card";
import { Skeleton } from "../components/ui/Skeleton";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { fmtNumber, fmtTimestamp } from "../lib/format";
import type { ReactNode } from "react";

export function DashboardView() {
  const overview = useQuery({ queryKey: ["overview"], queryFn: api.overview });
  const byType = useQuery({ queryKey: ["by-type", 12], queryFn: () => api.byType(12) });
  const byAccount = useQuery({
    queryKey: ["by-account", 10],
    queryFn: () => api.byAccount(10),
  });

  const refetchAll = () => {
    overview.refetch();
    byType.refetch();
    byAccount.refetch();
  };

  return (
    <div className="px-10 py-8 max-w-[1400px] mx-auto space-y-8">
      <div className="flex items-end justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-[var(--color-fg-muted)] font-semibold">
            <Activity size={12} className="text-[var(--color-accent-500)]" />
            Live snapshot
          </div>
          <h1 className="mt-1 text-3xl font-bold tracking-tight text-[var(--color-fg-primary)]">
            Estate overview
          </h1>
          <p className="mt-1 text-sm text-[var(--color-fg-muted)]">
            Sourced from the AWS Config flat table, refreshed every minute.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={refetchAll}>
          <RefreshCcw size={14} />
          Refresh
        </Button>
      </div>

      {/* ---- KPI cards ---- */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <KpiCard
          label="Total resources"
          value={overview.data?.total_resources}
          icon={<Boxes size={16} />}
          loading={overview.isLoading}
        />
        <KpiCard
          label="Distinct accounts"
          value={overview.data?.distinct_accounts}
          icon={<Building2 size={16} />}
          loading={overview.isLoading}
        />
        <KpiCard
          label="Resource types"
          value={overview.data?.distinct_resource_types}
          icon={<Layers3 size={16} />}
          loading={overview.isLoading}
        />
        <KpiCard
          label="Regions"
          value={overview.data?.distinct_regions}
          icon={<Globe2 size={16} />}
          loading={overview.isLoading}
        />
      </div>

      {/* ---- middle row: chart + sidebar ---- */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2">
          <CardHeader
            title="Top resource types"
            subtitle="By count of rows currently in cinq.operational_live"
            actions={
              byType.data ? (
                <Badge tone="accent">{byType.data.items.length} types</Badge>
              ) : null
            }
          />
          <CardBody>
            {byType.isLoading ? (
              <ChartSkeleton />
            ) : byType.error ? (
              <ErrorState message="Failed to load resource types" />
            ) : (
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={byType.data?.items ?? []}
                    layout="vertical"
                    margin={{ top: 4, right: 16, left: 0, bottom: 4 }}
                  >
                    <CartesianGrid stroke="#eef2f7" horizontal={false} />
                    <XAxis
                      type="number"
                      stroke="#94a3b8"
                      fontSize={11}
                      tickLine={false}
                      axisLine={false}
                    />
                    <YAxis
                      type="category"
                      dataKey="resource_type"
                      stroke="#475569"
                      fontSize={11}
                      tickLine={false}
                      axisLine={false}
                      width={210}
                      tickFormatter={(v: string) => v.replace("AWS::", "")}
                    />
                    <Tooltip
                      cursor={{ fill: "#eef2ff" }}
                      contentStyle={{
                        border: "1px solid #e5e7eb",
                        borderRadius: 8,
                        boxShadow: "0 4px 16px -4px rgba(15,23,42,0.1)",
                        fontSize: 12,
                      }}
                      formatter={(v) => [fmtNumber(Number(v)), "rows"]}
                    />
                    <Bar
                      dataKey="resource_count"
                      fill="#6366f1"
                      radius={[0, 4, 4, 0]}
                      maxBarSize={18}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Snapshot freshness"
            subtitle="When the underlying view last refreshed"
          />
          <CardBody>
            {overview.isLoading ? (
              <div className="space-y-3">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-3 w-48" />
              </div>
            ) : overview.error ? (
              <ErrorState message="Failed to load snapshot info" />
            ) : (
              <div className="space-y-5">
                <Stat label="Earliest row" value={fmtTimestamp(overview.data?.first_seen_at)} />
                <Stat label="Latest row"   value={fmtTimestamp(overview.data?.last_seen_at)} />
                <div className="pt-2 border-t border-[var(--color-border-subtle)]">
                  <Stat
                    label="Athena query ID"
                    value={
                      <span className="font-mono text-[11px]">
                        {overview.data?.athena_query_id ?? "—"}
                      </span>
                    }
                  />
                </div>
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      {/* ---- accounts table ---- */}
      <Card>
        <CardHeader
          title="Top accounts"
          subtitle="Highest resource count first"
          actions={
            byAccount.data ? (
              <Badge tone="accent">{byAccount.data.items.length} of {overview.data?.distinct_accounts ?? "?"}</Badge>
            ) : null
          }
        />
        <div className="overflow-x-auto">
          {byAccount.isLoading ? (
            <div className="px-6 py-6 space-y-2">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          ) : byAccount.error ? (
            <div className="p-6">
              <ErrorState message="Failed to load accounts" />
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-[var(--color-bg-app)] text-xs uppercase tracking-wider text-[var(--color-fg-muted)]">
                <tr>
                  <th className="text-left font-semibold px-6 py-3">Account</th>
                  <th className="text-right font-semibold px-6 py-3">Resources</th>
                  <th className="text-right font-semibold px-6 py-3">Distinct types</th>
                  <th className="text-right font-semibold px-6 py-3">Regions</th>
                </tr>
              </thead>
              <tbody>
                {byAccount.data?.items.map((a: AccountCount) => (
                  <tr
                    key={a.account_id}
                    className="border-t border-[var(--color-border-subtle)] hover:bg-[var(--color-accent-50)]/50"
                  >
                    <td className="px-6 py-3 font-mono text-[13px] text-[var(--color-fg-primary)]">
                      {a.account_id}
                    </td>
                    <td className="px-6 py-3 text-right tabular-nums">
                      {fmtNumber(a.resource_count)}
                    </td>
                    <td className="px-6 py-3 text-right tabular-nums text-[var(--color-fg-secondary)]">
                      {fmtNumber(a.distinct_resource_types)}
                    </td>
                    <td className="px-6 py-3 text-right tabular-nums text-[var(--color-fg-secondary)]">
                      {fmtNumber(a.distinct_regions)}
                    </td>
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

// ---------- helpers ----------

function KpiCard({
  label,
  value,
  icon,
  loading,
}: {
  label: string;
  value: number | undefined;
  icon: ReactNode;
  loading: boolean;
}) {
  return (
    <Card className="overflow-hidden">
      <CardBody className="p-5">
        <div className="flex items-center justify-between">
          <span className="text-[11px] uppercase tracking-wider font-semibold text-[var(--color-fg-muted)]">
            {label}
          </span>
          <span className="size-7 rounded-md bg-[var(--color-accent-50)] text-[var(--color-accent-600)] flex items-center justify-center">
            {icon}
          </span>
        </div>
        <div className="mt-3 h-9 flex items-end">
          {loading ? (
            <Skeleton className="h-7 w-24" />
          ) : (
            <span className="text-3xl font-bold tabular-nums tracking-tight text-[var(--color-fg-primary)]">
              {fmtNumber(value)}
            </span>
          )}
        </div>
      </CardBody>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider font-semibold text-[var(--color-fg-muted)]">
        {label}
      </div>
      <div className="mt-1 text-sm text-[var(--color-fg-primary)]">{value}</div>
    </div>
  );
}

function ChartSkeleton() {
  return (
    <div className="h-80 flex items-end gap-2 px-4">
      {Array.from({ length: 12 }).map((_, i) => (
        <div key={i} className="skeleton flex-1 rounded" style={{ height: `${30 + ((i * 47) % 60)}%` }} />
      ))}
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-[var(--color-danger-700)]">
      <AlertCircle size={16} />
      {message}
    </div>
  );
}
