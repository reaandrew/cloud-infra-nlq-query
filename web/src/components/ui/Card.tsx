import { type HTMLAttributes, type ReactNode } from "react";
import { cn } from "../../lib/cn";

export function Card({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "bg-white border border-[var(--color-border-subtle)] rounded-xl shadow-[var(--shadow-card)]",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  className,
  title,
  subtitle,
  actions,
}: {
  className?: string;
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div
      className={cn(
        "flex items-start justify-between gap-4 px-6 py-5 border-b border-[var(--color-border-subtle)]",
        className,
      )}
    >
      <div className="min-w-0">
        <div className="text-sm font-semibold text-[var(--color-fg-primary)] tracking-tight">
          {title}
        </div>
        {subtitle ? (
          <div className="mt-0.5 text-xs text-[var(--color-fg-muted)]">{subtitle}</div>
        ) : null}
      </div>
      {actions ? <div className="shrink-0">{actions}</div> : null}
    </div>
  );
}

export function CardBody({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return <div className={cn("p-6", className)}>{children}</div>;
}
