"use client";

import * as React from "react";
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog";
import { XIcon } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

type SheetSide = "bottom" | "left" | "right";

const sideClasses: Record<SheetSide, string> = {
  bottom:
    "inset-x-0 bottom-0 top-auto max-h-[85dvh] w-full rounded-t-2xl border-t data-open:slide-in-from-bottom data-closed:slide-out-to-bottom",
  left: "inset-y-0 left-0 h-full w-[min(100vw,20rem)] rounded-r-2xl border-r data-open:slide-in-from-left data-closed:slide-out-to-left",
  right: "inset-y-0 right-0 h-full w-[min(100vw,20rem)] rounded-l-2xl border-l data-open:slide-in-from-right data-closed:slide-out-to-right",
};

function Sheet({ ...props }: DialogPrimitive.Root.Props) {
  return <DialogPrimitive.Root data-slot="sheet" {...props} />;
}

function SheetTrigger({ ...props }: DialogPrimitive.Trigger.Props) {
  return <DialogPrimitive.Trigger data-slot="sheet-trigger" {...props} />;
}

function SheetClose({ ...props }: DialogPrimitive.Close.Props) {
  return <DialogPrimitive.Close data-slot="sheet-close" {...props} />;
}

function SheetContent({
  children,
  className,
  showCloseButton = true,
  side = "bottom",
  ...props
}: DialogPrimitive.Popup.Props & {
  showCloseButton?: boolean;
  side?: SheetSide;
}) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Backdrop
        className="fixed inset-0 z-50 bg-black/40 data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0"
      />
      <DialogPrimitive.Popup
        className={cn(
          "fixed z-50 grid gap-4 bg-background p-4 text-foreground shadow-lg outline-none duration-200 data-open:animate-in data-closed:animate-out",
          sideClasses[side],
          className,
        )}
        {...props}
      >
        {children}
        {showCloseButton ? (
          <DialogPrimitive.Close
            render={
              <Button className="absolute top-3 right-3" size="icon-sm" variant="ghost" />
            }
          >
            <XIcon className="size-4" />
            <span className="sr-only">Close</span>
          </DialogPrimitive.Close>
        ) : null}
      </DialogPrimitive.Popup>
    </DialogPrimitive.Portal>
  );
}

function SheetHeader({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("flex flex-col gap-1 pr-8", className)} {...props} />;
}

function SheetTitle({ className, ...props }: DialogPrimitive.Title.Props) {
  return (
    <DialogPrimitive.Title
      className={cn("text-base font-semibold tracking-tight", className)}
      {...props}
    />
  );
}

function SheetDescription({ className, ...props }: DialogPrimitive.Description.Props) {
  return (
    <DialogPrimitive.Description
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    />
  );
}

export { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger };
