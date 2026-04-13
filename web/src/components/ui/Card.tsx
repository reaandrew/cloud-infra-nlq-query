import { type HTMLAttributes, type ReactNode } from "react";
import { cn } from "../../lib/cn";

/**
 * GDS-styled card surface. Flat, sharp corners, single-pixel grey border,
 * no shadow. Header has a thick black bottom border to separate it from
 * the body.
 */

export function Card({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("bg-white border border-[var(--color-border)]", className)}
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
        "flex items-start justify-between gap-4 px-6 py-4 border-b border-[var(--color-border)]",
        className,
      )}
    >
      <div className="min-w-0">
        <div className="text-[19px] font-bold text-[var(--color-text)] leading-tight">
          {title}
        </div>
        {subtitle ? (
          <div className="mt-1 text-[14px] text-[var(--color-text-secondary)]">
            {subtitle}
          </div>
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
  return <div className={cn("p-5", className)}>{children}</div>;
}
