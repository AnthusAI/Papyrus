import Image from "next/image";
import { cn } from "@/lib/utils";

export function Wordmark({ inverse = false, className }: { inverse?: boolean; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", inverse && "text-papyrus", className)}>
      <span className={cn("grid h-10 w-9 place-items-center rounded-t-full", inverse ? "bg-papyrus" : "bg-reed/12")}>
        <Image src="/papyrus-plant.png" alt="" width={23} height={30} className="h-7 w-auto" priority />
      </span>
      <span className="font-display text-[1.65rem] font-semibold leading-none tracking-[-0.035em]">Papyrus</span>
    </span>
  );
}
