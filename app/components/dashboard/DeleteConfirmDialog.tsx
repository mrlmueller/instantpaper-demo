"use client";

import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog";

interface DeleteConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  type: "quelle" | "kapitel" | "projekt";
  name: string;
  onConfirm: () => void;
}

export function DeleteConfirmDialog({
  open,
  onOpenChange,
  type,
  name,
  onConfirm,
}: DeleteConfirmDialogProps) {
  const typeLabel = type === "quelle" ? "Quelle" : type === "kapitel" ? "Kapitel" : "Projekt";
  const isArchive = type === "projekt";
  const actionLabel = isArchive ? "archivieren" : "löschen";
  const confirmLabel = isArchive ? "Archivieren" : "Löschen";
  const warning =
    type === "quelle"
      ? "Diese Quelle wird aus allen Kapiteln entfernt, in denen sie zugewiesen ist."
      : type === "kapitel"
        ? "Alle Runs und generierten Texte für dieses Kapitel werden ebenfalls gelöscht."
        : "Das Projekt wird ausgeblendet und kann später im Tab \"Archiviert\" wiederhergestellt werden.";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md [&>button]:hidden">
        <DialogHeader className="pb-4 border-b">
          <DialogTitle className="flex items-center gap-2 text-lg">
            <div className="w-8 h-8 rounded-lg bg-destructive/10 flex items-center justify-center">
              <AlertTriangle className="h-4 w-4 text-destructive" />
            </div>
            {typeLabel} {actionLabel}?
          </DialogTitle>
          <DialogDescription className="pt-1">
            Bist du sicher, dass du <strong>&quot;{name}&quot;</strong> {actionLabel} möchtest? {warning}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="pt-4 border-t gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Abbrechen
          </Button>
          <Button variant="destructive" onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
