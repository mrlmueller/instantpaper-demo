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
  const warning =
    type === "quelle"
      ? "Diese Quelle wird aus allen Kapiteln entfernt, in denen sie zugewiesen ist."
      : type === "kapitel"
        ? "Alle Runs und generierten Texte für dieses Kapitel werden ebenfalls gelöscht."
        : "Alle Kapiteln, Quellen und Runs in diesem Projekt werden ebenfalls gelöscht.";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-destructive" />
            {typeLabel} löschen?
          </DialogTitle>
          <DialogDescription className="pt-2">
            Bist du sicher, dass du <strong>&quot;{name}&quot;</strong> löschen möchtest? {warning}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="mt-4">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Abbrechen
          </Button>
          <Button variant="destructive" onClick={onConfirm}>
            Löschen
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
