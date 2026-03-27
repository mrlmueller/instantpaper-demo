"use client";

import { useEffect, useMemo, useState } from "react";
import { CircleHelp } from "lucide-react";
import Image from "next/image";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

import type { HelpLang } from "./pipelineDetailsHelpContent";
import { PIPELINE_DETAILS_HELP } from "./pipelineDetailsHelpContent";

export function HelpPopover({
  helpKey,
  side = "bottom",
  align = "end",
  iconClassName,
  extra,
}: {
  helpKey: string;
  side?: "top" | "right" | "bottom" | "left";
  align?: "start" | "center" | "end";
  iconClassName?: string;
  extra?: { de?: React.ReactNode; en?: React.ReactNode };
}) {
  const entry = PIPELINE_DETAILS_HELP[helpKey];
  const [lang, setLang] = useState<HelpLang>("de");

  useEffect(() => {
    try {
      const l = (navigator.language || "").toLowerCase();
      if (l.startsWith("en")) setLang("en");
      else setLang("de");
    } catch {
      setLang("de");
    }
    // only run once when mounted
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const title = useMemo(() => {
    if (!entry) return "";
    return lang === "en" ? entry.title.en : entry.title.de;
  }, [entry, lang]);

  if (!entry) return null;

  const body = lang === "en" ? entry.body.en : entry.body.de;
  const images = entry.images || [];
  const extraBody = lang === "en" ? extra?.en : extra?.de;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`${lang === "en" ? "Info" : "Info"}: ${title}`}
          className="inline-flex items-center justify-center rounded-md text-muted-foreground hover:text-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background"
          onClick={(e) => e.stopPropagation()}
        >
          <CircleHelp className={iconClassName || "size-4"} />
        </button>
      </PopoverTrigger>
      <PopoverContent
        side={side}
        align={align}
        sideOffset={8}
        className="w-[min(760px,92vw)] p-0"
        onOpenAutoFocus={(e) => e.preventDefault()}
        onCloseAutoFocus={(e) => e.preventDefault()}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-border">
          <div className="min-w-0">
            <div className="text-sm font-semibold truncate">{title}</div>
            <div className="text-[11px] text-muted-foreground">
              <span className="font-mono">{helpKey}</span>
            </div>
          </div>
          <Tabs value={lang} onValueChange={(v) => setLang(v as HelpLang)}>
            <TabsList className="h-7">
              <TabsTrigger value="de" className="text-xs px-2">
                DE
              </TabsTrigger>
              <TabsTrigger value="en" className="text-xs px-2">
                EN
              </TabsTrigger>
            </TabsList>
          </Tabs>
        </div>

        <ScrollArea className="max-h-[62vh]">
          <div className="px-4 py-3 space-y-4">
            <div className="space-y-3">{body}</div>

            {images.length ? (
              <div className="space-y-2">
                <div className="text-xs font-semibold text-foreground">{lang === "en" ? "Examples" : "Beispiele"}</div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {images.map((img) => (
                      <div key={img.src} className="rounded-md border border-border bg-muted/10 overflow-hidden">
                        <div className="bg-background">
                        <Image
                          src={img.src}
                          alt={img.alt}
                          width={760}
                          height={420}
                          className="w-full h-auto block"
                        />
                      </div>
                      <div className="px-3 py-2 text-xs text-muted-foreground">
                        {lang === "en" ? img.caption.en : img.caption.de}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {extraBody ? (
              <div className="rounded-md border border-border bg-muted/10 px-3 py-2">
                <div className="text-xs font-semibold text-foreground mb-1">{lang === "en" ? "This run" : "Dieser Run"}</div>
                <div className="text-xs text-muted-foreground">{extraBody}</div>
              </div>
            ) : null}
          </div>
        </ScrollArea>
      </PopoverContent>
    </Popover>
  );
}
