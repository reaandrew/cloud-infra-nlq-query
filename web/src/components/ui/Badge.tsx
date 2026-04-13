import { type HTMLAttributes } from "react";
import { cn } from "../../lib/cn";

/**
 * GDS tag — sharp-cornered uppercase pill used for status / phase
 * labels. https://design-system.service.gov.uk/components/tag/
 */

type Tone = "blue" | "grey" | "green" | "yellow" | "red" | "orange" | "purple";

const toneStyles: Record<Tone, string> = {
  blue:   "bg-[var(--color-blue)] text-white",
  grey:   "bg-[var(--color-bg-grey-2)] text-[var(--color-text)]",
  green:  "bg-[var(--color-green)] text-white",
  yellow: "bg-[var(--color-yellow)] text-[var(--color-text)]",
  red:    "bg-[var(--color-red)] text-white",
  orange: "bg-[var(--color-orange)] text-white",
  purple: "bg-[var(--color-purple)] text-white",
};

interface Props extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
}

export function Badge({ tone = "blue", className, children, ...rest }: Props) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-1 text-[14px] font-bold uppercase tracking-wider whitespace-nowrap",
        toneStyles[tone],
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
}
