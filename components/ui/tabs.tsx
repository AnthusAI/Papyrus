"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

type TabsContextValue = {
  value: string;
  setValue: (value: string) => void;
};

const TabsContext = React.createContext<TabsContextValue | null>(null);

function useTabsContext(componentName: string): TabsContextValue {
  const context = React.useContext(TabsContext);
  if (!context) {
    throw new Error(`${componentName} must be used within <Tabs>.`);
  }
  return context;
}

function Tabs({
  children,
  className,
  defaultValue,
  onValueChange,
  value,
}: React.PropsWithChildren<{
  className?: string;
  defaultValue: string;
  onValueChange?: (value: string) => void;
  value?: string;
}>) {
  const [uncontrolledValue, setUncontrolledValue] = React.useState(defaultValue);
  const activeValue = value ?? uncontrolledValue;
  const setValue = React.useCallback(
    (nextValue: string) => {
      if (value === undefined) {
        setUncontrolledValue(nextValue);
      }
      onValueChange?.(nextValue);
    },
    [onValueChange, value],
  );

  return (
    <TabsContext.Provider value={{ value: activeValue, setValue }}>
      <div className={cn("flex flex-col gap-3", className)}>{children}</div>
    </TabsContext.Provider>
  );
}

function TabsList({
  children,
  className,
}: React.PropsWithChildren<{ className?: string }>) {
  return (
    <div
      aria-orientation="horizontal"
      className={cn(
        "inline-flex h-9 w-fit items-center rounded-lg bg-muted/50 p-1 text-muted-foreground",
        className,
      )}
      role="tablist"
    >
      {children}
    </div>
  );
}

function TabsTrigger({
  children,
  className,
  value,
}: React.PropsWithChildren<{ className?: string; value: string }>) {
  const context = useTabsContext("TabsTrigger");
  const active = context.value === value;
  return (
    <button
      aria-selected={active}
      className={cn(
        "inline-flex min-w-[7rem] items-center justify-center rounded-md px-3 py-1.5 text-sm font-medium transition-all",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[rgb(var(--ink-solid-rgb)_/_0.18)]",
        active
          ? "bg-primary text-primary-foreground shadow-sm"
          : "text-muted-foreground hover:text-foreground",
        className,
      )}
      data-state={active ? "active" : "inactive"}
      onClick={() => context.setValue(value)}
      role="tab"
      type="button"
    >
      {children}
    </button>
  );
}

function TabsContent({
  children,
  className,
  value,
}: React.PropsWithChildren<{ className?: string; value: string }>) {
  const context = useTabsContext("TabsContent");
  if (context.value !== value) return null;
  return (
    <div className={className} data-state="active" role="tabpanel">
      {children}
    </div>
  );
}

export { Tabs, TabsContent, TabsList, TabsTrigger };
