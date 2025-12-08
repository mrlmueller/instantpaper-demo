'use client';

import { useState } from 'react';
import type { Kapitel } from '@/app/actions/kapitels';
import type { Quelle } from '@/app/actions/quellen';
import { updateKapitelQuellen } from '@/app/actions/kapitels';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Checkbox } from '@/components/ui/checkbox';
import { toast } from 'sonner';
import { ListChecks } from 'lucide-react';

interface ManageKapitelQuellenDialogProps {
  kapitel: Kapitel;
  quellen: Quelle[];
}

export function ManageKapitelQuellenDialog({ kapitel, quellen }: ManageKapitelQuellenDialogProps) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string[]>(kapitel.quelleIds || []);
  const [loading, setLoading] = useState(false);

  const toggle = (id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const handleSave = async () => {
    setLoading(true);
    const result = await updateKapitelQuellen(kapitel.id, selected);
    if (result.success) {
      toast.success('Quellen wurden aktualisiert');
      window.location.reload();
    } else {
      toast.error('Konnte Quellen nicht aktualisieren', {
        description: result.error,
      });
    }
    setLoading(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button variant="ghost" size="sm" className="gap-2" onClick={() => setOpen(true)}>
        <ListChecks className="h-4 w-4" />
        Quellen verwalten
      </Button>

      <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Quellen verwalten</DialogTitle>
          <DialogDescription>
            Ordne Quellen dem Kapitel "{kapitel.title}" zu oder entferne sie.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {quellen.length === 0 ? (
            <p className="text-sm text-muted-foreground">Noch keine Quellen angelegt.</p>
          ) : (
            quellen.map((quelle) => (
              <label
                key={quelle.id}
                className="flex items-start gap-3 p-2 rounded-md hover:bg-muted/50 cursor-pointer"
              >
                <Checkbox
                  checked={selected.includes(quelle.id)}
                  onCheckedChange={() => toggle(quelle.id)}
                  className="mt-1"
                />
                <div className="flex-1">
                  <p className="font-medium text-sm">{quelle.title}</p>
                  <p className="text-xs text-muted-foreground line-clamp-2">
                    {quelle.content.substring(0, 120)}...
                  </p>
                </div>
              </label>
            ))
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={loading}>
            Abbrechen
          </Button>
          <Button onClick={handleSave} disabled={loading || quellen.length === 0}>
            {loading ? 'Speichere...' : 'Speichern'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
