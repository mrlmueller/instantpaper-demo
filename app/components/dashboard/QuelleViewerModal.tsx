"use client";

import { Copy, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
  const [viewingImage, setViewingImage] = useState<string | null>(null);

  const handleCopy = async () => {
    if (quelle) {
      await navigator.clipboard.writeText(quelle.text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const wordCount = quelle?.text.split(/\s+/).filter(Boolean).length || 0;

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-4xl max-h-[90vh] flex flex-col [&>button]:hidden">
          <DialogHeader className="flex-shrink-0 pr-0">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0 pr-2">
                <DialogTitle className="text-xl leading-tight text-balance">
                  {quelle?.name}
                </DialogTitle>
                <div className="text-sm text-muted-foreground mt-1">
                  {wordCount.toLocaleString("de-DE")} Wörter
                  {quelle?.images &&
                    quelle.images.length > 0 &&
                    ` · ${quelle.images.length} Bilder`}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Button variant="outline" size="sm" onClick={handleCopy}>
                  {copied ? (
                    <>
                      <Check className="h-4 w-4 mr-2 text-primary" />
                      Kopiert
                    </>
                  ) : (
                    <>
                      <Copy className="h-4 w-4 mr-2" />
                      Kopieren
                    </>
                  )}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onOpenChange(false)}
                  className="h-8 w-8 p-0"
                >
                  <X className="h-4 w-4" />
                  <span className="sr-only">Schließen</span>
                </Button>
              </div>
            </div>
          </DialogHeader>

          <div className="flex-1 overflow-y-auto mt-4 pr-2">
            {quelle?.images && quelle.images.length > 0 && (
              <div className="mb-6">
                <h3 className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">
                  Bilder
                </h3>
                <div className="grid grid-cols-4 gap-2">
                  {quelle.images.map((img, index) => (
                    <button
                      key={index}
                      onClick={() => setViewingImage(img)}
                      className="relative aspect-square rounded-md overflow-hidden border bg-muted hover:ring-2 hover:ring-primary/50 transition-all"
                    >
                      <img
                        src={img}
                        alt={`Bild ${index + 1}`}
                        className="w-full h-full object-cover"
                      />
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="text-foreground/90 leading-relaxed whitespace-pre-wrap text-sm">
              {quelle?.text}
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Image Zoom Dialog */}
      <Dialog open={viewingImage !== null} onOpenChange={() => setViewingImage(null)}>
        <DialogContent className="sm:max-w-5xl p-0 [&>button]:hidden bg-background border-0 shadow-2xl">
          <div className="relative flex items-center justify-center p-4">
            <img
              src={viewingImage || ""}
              alt="Vergrößertes Bild"
              className="max-w-full max-h-[85vh] object-contain rounded-lg"
            />
            <Button
              variant="secondary"
              size="sm"
              className="absolute top-6 right-6 shadow-lg"
              onClick={() => setViewingImage(null)}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
