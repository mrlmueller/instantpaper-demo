'use client';

import { useState } from 'react';
import { createQuelle } from '@/app/actions/quellen';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import { Plus } from 'lucide-react';

export function CreateQuelleDialog() {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!title.trim()) {
      toast.error('Titel ist erforderlich');
      return;
    }

    if (!content.trim()) {
      toast.error('Inhalt ist erforderlich');
      return;
    }

    setLoading(true);
    const result = await createQuelle(title.trim(), content.trim());

    if (result.success) {
      toast.success('Quelle wurde erstellt');
      setTitle('');
      setContent('');
      setOpen(false);
      window.location.reload();
    } else {
      toast.error('Quelle konnte nicht erstellt werden', {
        description: result.error,
      });
    }
    setLoading(false);
  };

  const wordCount = content.trim().split(/\s+/).filter(Boolean).length;
  const charCount = content.length;

  return (
    <>
      <Button onClick={() => setOpen(true)} size="lg" variant="outline">
        <Plus className="mr-2 h-5 w-5" />
        Neue Quelle
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Neue Quelle anlegen</DialogTitle>
            <DialogDescription>
              Lege eine Quelle an, die später Kapiteln zugeordnet werden kann.
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={handleSubmit} className="space-y-6">
            <div className="space-y-2">
              <Label htmlFor="title">Titel</Label>
              <Input
                id="title"
                placeholder="Titel der Quelle"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                disabled={loading}
                required
              />
            </div>

            <div className="space-y-2">
              <div className="flex justify-between items-center">
                <Label htmlFor="content">Inhalt</Label>
                <span className="text-sm text-gray-500">
                  {wordCount} Wörter · {charCount} Zeichen
                </span>
              </div>
              <Textarea
                id="content"
                placeholder="Füge den Quellentext hier ein..."
                value={content}
                onChange={(e) => setContent(e.target.value)}
                disabled={loading}
                required
                rows={14}
                className="resize-y min-h-[320px] font-mono text-sm"
              />
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
              <Button type="submit" disabled={loading}>
                {loading ? 'Erstellen...' : 'Quelle erstellen'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
