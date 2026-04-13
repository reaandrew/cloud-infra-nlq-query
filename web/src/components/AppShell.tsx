import { type ReactNode } from "react";
import { KeyRound, ExternalLink } from "lucide-react";
import { cn } from "../lib/cn";

export type ViewId = "query" | "how-it-works" | "how-this-was-made";

interface NavItem {
  id: ViewId;
  label: string;
}

const NAV: NavItem[] = [
  { id: "query", label: "Query" },
  { id: "how-it-works", label: "How it works" },
  { id: "how-this-was-made", label: "How this was made" },
];

interface AppShellProps {
  view: ViewId;
  onViewChange: (view: ViewId) => void;
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
    <div className="min-h-screen flex flex-col bg-white">
      {/* ---- header ---- */}
      <header className="bg-[var(--color-header-bg)] border-b-[10px] border-[var(--color-blue)]">
        <div className="max-w-[1100px] mx-auto px-4 md:px-8 py-3 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="px-2 py-1 bg-white text-[var(--color-text)] text-[15px] font-bold tracking-tight">
              DEMO
            </div>
            <span className="text-white text-[19px] font-bold tracking-tight">
              AWS Config NLQ
            </span>
          </div>
          <button
            onClick={onOpenApiKeyDialog}
            className="text-white hover:underline text-[16px] flex items-center gap-2"
          >
            <KeyRound size={16} />
            <span>API key</span>
            <span
              className={cn(
                "inline-block size-2",
                apiKeyStatus === "ok" ? "bg-[var(--color-green)]" : "bg-[var(--color-orange)]",
              )}
            />
          </button>
        </div>
      </header>

      {/* ---- phase banner ---- */}
      <div className="bg-white border-b border-[var(--color-border)]">
        <div className="max-w-[1100px] mx-auto px-4 md:px-8 py-3">
          <p className="text-[16px] text-[var(--color-text)]">
            <strong className="inline-block bg-[var(--color-blue)] text-white text-[14px] font-bold uppercase tracking-wider px-2 py-0.5 mr-3 align-middle">
              Demo
            </strong>
            <span>
              This is a demonstration service. It runs against a synthetic AWS
              Config dataset.
            </span>
          </p>
        </div>
      </div>

      {/* ---- nav ---- */}
      <nav aria-label="Sections" className="border-b border-[var(--color-border)]">
        <div className="max-w-[1100px] mx-auto px-4 md:px-8">
          <ul className="flex items-end gap-0 -mb-px flex-wrap">
            {NAV.map((item) => {
              const active = view === item.id;
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => onViewChange(item.id)}
                    className={cn(
                      "px-6 py-4 text-[19px] font-bold relative",
                      active
                        ? "text-[var(--color-text)]"
                        : "text-[var(--color-link)] hover:text-[var(--color-link-hover)]",
                    )}
                  >
                    {item.label}
                    {active && (
                      <span
                        className="absolute inset-x-0 bottom-0 h-[4px] bg-[var(--color-blue)]"
                        aria-hidden
                      />
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      </nav>

      {/* ---- main ---- */}
      <main className="flex-1 bg-white">{children}</main>

      {/* ---- footer ---- */}
      <footer className="border-t-2 border-[var(--color-blue)] bg-[var(--color-bg-grey)]">
        <div className="max-w-[1100px] mx-auto px-4 md:px-8 py-6">
          <p className="text-[16px] text-[var(--color-text-secondary)]">
            <strong className="font-bold text-[var(--color-text)]">DEMO</strong>{" "}
            — a public demonstration of an Athena-backed natural-language query
            layer over AWS Config. No real account data, no warranty. Source on{" "}
            <a
              href="https://github.com/reaandrew/cloud-infra-nlq-query"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1"
            >
              GitHub
              <ExternalLink size={13} />
            </a>
            .
          </p>
        </div>
      </footer>
    </div>
  );
}
