import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full px-3 py-1.5 font-mono text-[0.67rem] font-semibold uppercase tracking-[0.13em]",
  {
    variants: {
      variant: {
        default: "bg-ink text-papyrus",
        reed: "bg-reed text-white",
        nile: "bg-nile text-white",
        outline: "border border-ink/20 bg-papyrus text-ink",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}
