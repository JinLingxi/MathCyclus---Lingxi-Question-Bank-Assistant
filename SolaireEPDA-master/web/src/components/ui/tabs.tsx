import type { ComponentPropsWithoutRef } from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "../../lib/utils";

const Tabs = TabsPrimitive.Root;

const TabsList = ({ className, ...props }: ComponentPropsWithoutRef<typeof TabsPrimitive.List>) => (
  <TabsPrimitive.List
    className={cn(
      "inline-flex h-9 items-center justify-center rounded-lg bg-slate-100 p-1 text-slate-600",
      className,
    )}
    {...props}
  />
);

const TabsTrigger = ({ className, ...props }: ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>) => (
  <TabsPrimitive.Trigger
    className={cn(
      "inline-flex flex-1 items-center justify-center whitespace-nowrap rounded-md px-3 py-1 text-sm font-medium ring-offset-white transition-all",
      "data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-sm",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2",
      className,
    )}
    {...props}
  />
);

const TabsContent = ({ className, ...props }: ComponentPropsWithoutRef<typeof TabsPrimitive.Content>) => (
  <TabsPrimitive.Content
    className={cn("mt-3 ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400", className)}
    {...props}
  />
);

export { Tabs, TabsList, TabsTrigger, TabsContent };
