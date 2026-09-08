import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "group inline-flex min-h-12 items-center justify-center gap-2 rounded-full px-6 font-body text-sm font-extrabold transition duration-200 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-nile/30 disabled:pointer-events-none disabled:opacity-55",
  {
    variants: {
      variant: {
        default:
          "bg-oxide text-white shadow-[5px_5px_0_var(--ink)] hover:-translate-y-0.5 hover:shadow-[7px_7px_0_var(--ink)]",
        ink: "bg-ink text-papyrus hover:bg-nile hover:text-white",
        outline:
          "border border-ink/25 bg-papyrus/70 text-ink hover:border-ink hover:bg-sheet",
        ghost: "bg-transparent text-ink hover:bg-ink/5",
      },
      size: {
        default: "h-12",
        sm: "h-11 px-4 text-xs",
        lg: "h-14 px-8 text-base",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Component = asChild ? Slot : "button";
    return (
      <Component
        ref={ref}
        className={cn(buttonVariants({ variant, size, className }))}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
