import * as React from "react";
import { cn } from "@/lib/utils";

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className, type, ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      className={cn(
        "flex h-13 min-h-12 w-full rounded-xl border border-ink/20 bg-papyrus px-4 font-body text-base text-ink outline-none placeholder:text-muted/65 focus-visible:border-nile focus-visible:ring-4 focus-visible:ring-nile/15",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export { Input };
