import { type ReactNode } from "react";
import {
  LayoutDashboard,
  Sparkles,
  CircleDot,
  KeyRound,
  Activity,
  ExternalLink,
} from "lucide-react";
import { cn } from "../lib/cn";

export type ViewId = "dashboard" | "query";

interface AppShellProps {
  view: ViewId;
  onViewChange: (v: ViewId) => void;
  apiKeyStatus: "ok" | "missing";
  onOpenApiKeyDialog: () => void;
  children: ReactNode;
}

export function AppShell({
  view,
  onViewChange,
  apiKeyStatus,
  onOpenApiKeyDialog,
  children,
}: AppShellProps) {
  return (
    <div className="min-h-screen flex">
      {/* ---- sidebar ---- */}
      <aside className="w-64 shrink-0 bg-[var(--color-bg-sidebar)] text-[var(--color-fg-sidebar)] border-r border-[var(--color-border-sidebar)] flex flex-col">
        <div className="px-6 pt-6 pb-8">
          <div className="flex items-center gap-2.5">
            <div className="size-9 rounded-lg bg-[var(--color-bg-sidebar-active)] flex items-center justify-center">
              <Activity size={18} className="text-[var(--color-accent-500)]" />
            </div>
            <div>
              <div className="text-sm font-semibold tracking-tight text-white">cinq</div>
              <div className="text-[11px] text-[var(--color-fg-sidebar-muted)] tracking-wide uppercase">
                NLQ for AWS Config
              </div>
            </div>
          </div>
        </div>

        <nav className="px-3 flex-1 space-y-1">
          <NavLink
            active={view === "dashboard"}
            icon={<LayoutDashboard size={16} />}
            onClick={() => onViewChange("dashboard")}
          >
            Dashboard
          </NavLink>
          <NavLink
            active={view === "query"}
            icon={<Sparkles size={16} />}
            onClick={() => onViewChange("query")}
          >
            Query
          </NavLink>
        </nav>

        <div className="px-4 pb-5 pt-3 border-t border-[var(--color-border-sidebar)] space-y-3">
          <button
            onClick={onOpenApiKeyDialog}
            className="w-full flex items-center justify-between px-3 py-2 rounded-md text-xs text-[var(--color-fg-sidebar-muted)] hover:bg-[var(--color-bg-sidebar-elevated)] hover:text-white transition"
          >
            <span className="flex items-center gap-2">
              <KeyRound size={14} />
              <span>API key</span>
            </span>
            <span className="flex items-center gap-1">
              <CircleDot
                size={12}
                className={cn(
                  apiKeyStatus === "ok" ? "text-emerald-400" : "text-amber-400",
                )}
              />
              <span>{apiKeyStatus === "ok" ? "set" : "missing"}</span>
            </span>
          </button>
          <a
            href="https://github.com/reaandrew/cloud-infra-nlq-query"
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 px-3 py-1 text-[11px] text-[var(--color-fg-sidebar-muted)] hover:text-white"
          >
            <ExternalLink size={11} />
            <span>cloud-infra-nlq-query</span>
          </a>
        </div>
      </aside>

      {/* ---- main ---- */}
      <main className="flex-1 min-w-0 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto">{children}</div>
      </main>
    </div>
  );
}

function NavLink({
  active,
  icon,
  onClick,
  children,
}: {
  active?: boolean;
  icon: ReactNode;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors",
        active
          ? "bg-[var(--color-bg-sidebar-active)] text-white"
          : "text-[var(--color-fg-sidebar-muted)] hover:bg-[var(--color-bg-sidebar-elevated)] hover:text-white",
      )}
    >
      <span
        className={cn(
          "shrink-0",
          active ? "text-[var(--color-accent-500)]" : "text-[var(--color-fg-sidebar-muted)]",
        )}
      >
        {icon}
      </span>
      <span>{children}</span>
    </button>
  );
}
