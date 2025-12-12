"use client";

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Copy, Check, X } from "lucide-react";
import { useState } from "react";
import type { Quelle } from "@/app/types/ui";

interface QuelleViewerModalProps {
  quelle: Quelle | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function QuelleViewerModal({
  quelle,
  open,
  onOpenChange,
}: QuelleViewerModalProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    if (!quelle) return;
    await navigator.clipboard.writeText(quelle.text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const wordCount = quelle?.text
    ? quelle.text.split(/\s+/).filter(Boolean).length
    : 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl max-h-[85vh] overflow-y-auto [&>button]:hidden">
        <DialogHeader className="pb-4 border-b">
          <div className="flex items-center justify-between">
            <DialogTitle className="text-xl">{quelle?.name}</DialogTitle>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => onOpenChange(false)}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
          <div className="flex items-center gap-3 text-sm text-muted-foreground mt-2">
            <span>{wordCount.toLocaleString("de-DE")} Wörter</span>
          </div>
        </DialogHeader>

        <div className="space-y-6 py-4">
          {/* Image Grid Placeholder (mockup only) */}
          <div className="grid grid-cols-4 gap-3">
            {/* Show placeholder images for demo */}
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="aspect-square rounded-lg bg-muted flex items-center justify-center border border-border"
              >
                <span className="text-xs text-muted-foreground">
                  Bild {i}
                </span>
              </div>
            ))}
          </div>

          {/* Text Content */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium">Text</h3>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleCopy}
                className="h-8"
              >
                {copied ? (
                  <>
                    <Check className="h-4 w-4 mr-2" />
                    Kopiert!
                  </>
                ) : (
                  <>
                    <Copy className="h-4 w-4 mr-2" />
                    Text kopieren
                  </>
                )}
              </Button>
            </div>
            <div className="prose prose-sm max-w-none dark:prose-invert">
              <p className="text-sm leading-relaxed whitespace-pre-wrap">
                {quelle?.text}
              </p>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
