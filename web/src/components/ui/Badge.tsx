import { type HTMLAttributes } from "react";
import { cn } from "../../lib/cn";

type Tone = "neutral" | "accent" | "success" | "warning" | "danger";

const toneStyles: Record<Tone, string> = {
  neutral: "bg-slate-100 text-slate-700 border-slate-200",
  accent: "bg-[var(--color-accent-50)] text-[var(--color-accent-700)] border-[var(--color-accent-200)]",
  success: "bg-[var(--color-success-50)] text-[var(--color-success-700)] border-emerald-200",
  warning: "bg-[var(--color-warning-50)] text-[var(--color-warning-700)] border-amber-200",
  danger: "bg-[var(--color-danger-50)] text-[var(--color-danger-700)] border-red-200",
};

interface Props extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
}

export function Badge({ tone = "neutral", className, children, ...rest }: Props) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full border whitespace-nowrap",
        toneStyles[tone],
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
}
