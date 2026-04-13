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
        className="absolute inset-0 bg-[var(--color-text)]/70"
        onClick={closeable ? onClose : undefined}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="dialog-title"
        className={cn(
          "relative bg-white border border-[var(--color-border)] w-full max-w-xl",
          className,
        )}
      >
        <div className="flex items-start justify-between gap-5 px-8 pt-7 pb-4">
          <div className="min-w-0">
            <h2
              id="dialog-title"
              className="text-[24px] font-bold text-[var(--color-text)] leading-tight"
            >
              {title}
            </h2>
            {description ? (
              <p className="mt-2 text-[16px] text-[var(--color-text-secondary)]">
                {description}
              </p>
            ) : null}
          </div>
          {closeable ? (
            <button
              onClick={onClose}
              className="shrink-0 -mt-1 -mr-2 p-2 text-[var(--color-text)] hover:bg-[var(--color-bg-grey)]"
              aria-label="Close"
            >
              <X size={20} />
            </button>
          ) : null}
        </div>
        <div className="px-8 pb-8">{children}</div>
      </div>
    </div>
  );
}
