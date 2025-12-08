'use client';

import { useState } from 'react';
import type { Quelle } from '@/app/actions/quellen';
import { deleteQuelle } from '@/app/actions/quellen';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { toast } from 'sonner';
import { Trash2, BookOpen } from 'lucide-react';

export function QuellenList({ initialQuellen }: { initialQuellen: Quelle[] }) {
  const [quellen, setQuellen] = useState(initialQuellen);
  const [selectedQuelle, setSelectedQuelle] = useState<Quelle | null>(null);
  const [loading, setLoading] = useState(false);

  const handleDelete = async (id: string) => {
    if (!confirm('Diese Quelle wirklich löschen?')) {
      return;
    }

    setLoading(true);
    const result = await deleteQuelle(id);

    if (result.success) {
      setQuellen(quellen.filter((q) => q.id !== id));
      toast.success('Quelle gelöscht');
      if (selectedQuelle?.id === id) {
        setSelectedQuelle(null);
      }
    } else {
      toast.error('Quelle konnte nicht gelöscht werden', {
        description: result.error,
      });
    }
    setLoading(false);
  };

  const getPreview = (content: string) => {
    const firstSentence = content.split(/[.!?]/)[0];
    const preview = firstSentence.length > 150 ? content.substring(0, 150) : firstSentence;
    return preview.trim() + '...';
  };

  if (quellen.length === 0) {
    return (
      <div className="text-center py-8">
        <BookOpen className="mx-auto h-10 w-10 text-gray-400" />
        <h3 className="mt-2 text-sm font-semibold text-gray-900">Noch keine Quellen</h3>
        <p className="mt-1 text-sm text-gray-500">
          Lege zuerst Quellen an und ordne sie danach Kapiteln zu.
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {quellen.map((quelle) => (
          <div
            key={quelle.id}
            className="border rounded-lg p-5 hover:shadow-lg transition-all cursor-pointer bg-white"
            onClick={() => setSelectedQuelle(quelle)}
          >
            <h3 className="font-bold text-lg mb-2 line-clamp-2">{quelle.title}</h3>
            <p className="text-sm text-gray-600 mb-4 line-clamp-2">
              {getPreview(quelle.content)}
            </p>
            <div className="flex justify-between items-center text-xs text-gray-400">
              <span>{new Date(quelle.createdAt).toLocaleDateString()}</span>
              <Button
                variant="ghost"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  handleDelete(quelle.id);
                }}
                disabled={loading}
                className="h-8 w-8 p-0 text-red-600 hover:text-red-700 hover:bg-red-50"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          </div>
        ))}
      </div>

      <Dialog open={!!selectedQuelle} onOpenChange={() => setSelectedQuelle(null)}>
        <DialogContent className="max-w-4xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="text-2xl">{selectedQuelle?.title}</DialogTitle>
            <DialogDescription>
              Erstellt: {selectedQuelle?.createdAt ? new Date(selectedQuelle.createdAt).toLocaleString() : 'Unbekannt'}
              {' · '}
              {selectedQuelle?.content ? selectedQuelle.content.trim().split(/\s+/).filter(Boolean).length : 0} Wörter
            </DialogDescription>
          </DialogHeader>
          <div className="mt-6 prose prose-sm max-w-none">
            <p className="whitespace-pre-wrap leading-relaxed">{selectedQuelle?.content}</p>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
