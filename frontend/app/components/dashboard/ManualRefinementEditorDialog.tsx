"use client";

import { useMemo, useState } from "react";
import { Check, RotateCcw, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";

type ManualRefinementEditorDialogProps = {
  open: boolean;
  title: string;
  initialText: string;
  saving: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (text: string) => void;
};

export function ManualRefinementEditorDialog({
  open,
  title,
  initialText,
  saving,
  onOpenChange,
  onSave,
}: ManualRefinementEditorDialogProps) {
  const [text, setText] = useState(initialText);

  const trimmed = text.trim();
  const hasChanges = text !== initialText;
  const wordCount = useMemo(() => trimmed.split(/\s+/).filter(Boolean).length, [trimmed]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="!w-[88vw] !max-w-[88vw] h-[88vh] flex flex-col gap-0 p-0" showCloseButton={false}>
        <DialogHeader className="border-b px-6 py-4 shrink-0">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <DialogTitle className="text-lg leading-tight">{title}</DialogTitle>
              <div className="mt-1 text-sm text-muted-foreground">
                {wordCount.toLocaleString("de-DE")} Wörter · {text.length.toLocaleString("de-DE")} Zeichen
              </div>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => onOpenChange(false)}
              disabled={saving}
              className="h-8 w-8 shrink-0 p-0"
            >
              <X className="h-4 w-4" />
              <span className="sr-only">Schließen</span>
            </Button>
          </div>
        </DialogHeader>

        <div className="flex-1 min-h-0 bg-muted/20 p-4">
          <Textarea
            value={text}
            onChange={(event) => setText(event.target.value)}
            className="h-full min-h-full resize-none rounded-md border bg-background px-5 py-4 text-[15px] leading-7 text-foreground shadow-sm focus-visible:ring-2"
            spellCheck
            autoFocus
            disabled={saving}
          />
        </div>

        <div className="flex items-center justify-between gap-3 border-t bg-background px-6 py-4 shrink-0">
          <Button
            type="button"
            variant="outline"
            onClick={() => setText(initialText)}
            disabled={saving || !hasChanges}
            className="bg-transparent"
          >
            <RotateCcw className="mr-2 h-4 w-4" />
            Zurücksetzen
          </Button>
          <div className="flex items-center gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving} className="bg-transparent">
              Abbrechen
            </Button>
            <Button type="button" onClick={() => onSave(text)} disabled={saving || !trimmed || !hasChanges}>
              <Check className="mr-2 h-4 w-4" />
              Änderungen speichern
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
