import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/cn";

/**
 * GDS button. Sharp corners, GDS green for primary, secondary is a
 * grey-bordered outline button. The signature green button has the
 * 2px shadow underneath that the GDS design system uses to indicate
 * a clickable surface.
 *
 * Source: https://design-system.service.gov.uk/components/button/
 */

type Variant = "primary" | "secondary" | "warning" | "danger";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  full?: boolean;
}

const variantStyles: Record<Variant, string> = {
  primary: cn(
    "bg-[var(--color-green)] text-white",
    "shadow-[0_2px_0_var(--color-green-shadow)]",
    "hover:bg-[var(--color-green-hover)]",
    "active:translate-y-[2px] active:shadow-none",
  ),
  secondary: cn(
    "bg-[var(--color-bg-grey)] text-[var(--color-text)]",
    "shadow-[0_2px_0_#929191]",
    "hover:bg-[var(--color-bg-grey-2)]",
    "active:translate-y-[2px] active:shadow-none",
  ),
  warning: cn(
    "bg-[var(--color-orange)] text-white",
    "shadow-[0_2px_0_#7a3a1c]",
    "hover:bg-[#d65a1a]",
    "active:translate-y-[2px] active:shadow-none",
  ),
  danger: cn(
    "bg-[var(--color-red)] text-white",
    "shadow-[0_2px_0_#71190a]",
    "hover:bg-[#aa291a]",
    "active:translate-y-[2px] active:shadow-none",
  ),
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", full = false, className, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center gap-2",
        "px-4 py-3 text-[19px] font-bold leading-none border-0",
        "transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
        full && "w-full",
        variantStyles[variant],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
});
