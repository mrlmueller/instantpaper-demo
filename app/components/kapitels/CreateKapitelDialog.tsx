'use client';

import { useState } from 'react';
import { createKapitel } from '@/app/actions/kapitels';
import type { Quelle } from '@/app/actions/quellen';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import { toast } from 'sonner';
import { Plus } from 'lucide-react';

interface CreateKapitelDialogProps {
  quellen: Quelle[];
}

export function CreateKapitelDialog({ quellen }: CreateKapitelDialogProps) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [selectedQuellen, setSelectedQuellen] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  const toggle = (id: string) => {
    setSelectedQuellen((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) {
      toast.error('Titel ist erforderlich');
      return;
    }

    setLoading(true);
    const result = await createKapitel(title.trim(), selectedQuellen);
    if (result.success) {
      toast.success('Kapitel erstellt');
      setTitle('');
      setSelectedQuellen([]);
      setOpen(false);
      window.location.reload();
    } else {
      toast.error('Kapitel konnte nicht erstellt werden', {
        description: result.error,
      });
    }
    setLoading(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="lg" className="gap-2">
          <Plus className="h-5 w-5" />
          Neues Kapitel
        </Button>
      </DialogTrigger>

      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Neues Kapitel erstellen</DialogTitle>
          <DialogDescription>
            Benenne das Kapitel und wähle Quellen, die dazugehört sollen.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="kapitel-title">Titel</Label>
            <Input
              id="kapitel-title"
              placeholder="z.B. 2.3 Forschung zu XY"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              disabled={loading}
            />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Quellen zuordnen ({selectedQuellen.length})</Label>
              {quellen.length > 0 && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    setSelectedQuellen(
                      selectedQuellen.length === quellen.length ? [] : quellen.map((q) => q.id)
                    )
                  }
                >
                  {selectedQuellen.length === quellen.length ? 'Alle abwählen' : 'Alle wählen'}
                </Button>
              )}
            </div>
            {quellen.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Noch keine Quellen verfügbar. Lege zuerst Quellen an.
              </p>
            ) : (
              <div className="border rounded-lg max-h-72 overflow-y-auto divide-y">
                {quellen.map((quelle) => (
                  <label
                    key={quelle.id}
                    className="flex items-start gap-3 p-3 hover:bg-muted/50 cursor-pointer"
                  >
                    <Checkbox
                      checked={selectedQuellen.includes(quelle.id)}
                      onCheckedChange={() => toggle(quelle.id)}
                      className="mt-1"
                    />
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-sm line-clamp-1">{quelle.title}</p>
                      <p className="text-xs text-muted-foreground line-clamp-2">
                        {quelle.content.substring(0, 100)}...
                      </p>
                    </div>
                  </label>
                ))}
              </div>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
              disabled={loading}
            >
              Abbrechen
            </Button>
            <Button type="submit" disabled={loading || !title.trim()}>
              {loading ? 'Erstellen...' : 'Kapitel erstellen'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
