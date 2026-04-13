import { useEffect, type ReactNode } from "react";
import { X } from "lucide-react";
import { cn } from "../../lib/cn";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
  closeable?: boolean;
  className?: string;
}

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  closeable = true,
  className,
}: DialogProps) {
  // Close on ESC
  useEffect(() => {
    if (!open || !closeable) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, closeable, onClose]);

  // Lock body scroll while open
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 animate-fade-in">
      <div
        className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm"
        onClick={closeable ? onClose : undefined}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="dialog-title"
        className={cn(
          "relative bg-white rounded-2xl shadow-[var(--shadow-elevated)] w-full max-w-lg",
          className,
        )}
      >
        <div className="flex items-start justify-between gap-4 px-6 pt-6 pb-3">
          <div className="min-w-0">
            <h2
              id="dialog-title"
              className="text-lg font-semibold text-[var(--color-fg-primary)] tracking-tight"
            >
              {title}
            </h2>
            {description ? (
              <p className="mt-1 text-sm text-[var(--color-fg-muted)]">{description}</p>
            ) : null}
          </div>
          {closeable ? (
            <button
              onClick={onClose}
              className="shrink-0 -mt-2 -mr-2 p-2 rounded-md text-[var(--color-fg-muted)] hover:bg-[var(--color-bg-app)] hover:text-[var(--color-fg-primary)]"
              aria-label="Close"
            >
              <X size={18} />
            </button>
          ) : null}
        </div>
        <div className="px-6 pb-6">{children}</div>
      </div>
    </div>
  );
}
