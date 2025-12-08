'use client';

import { useState } from 'react';
import type { Paper } from '@/app/actions/papers';
import { deletePaper } from '@/app/actions/papers';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { toast } from 'sonner';
import { Trash2, FileText } from 'lucide-react';

export function PapersList({ initialPapers }: { initialPapers: Paper[] }) {
  const [papers, setPapers] = useState(initialPapers);
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null);
  const [loading, setLoading] = useState(false);

  const handleDelete = async (id: string) => {
    if (!confirm('Are you sure you want to delete this paper?')) {
      return;
    }

    setLoading(true);
    const result = await deletePaper(id);

    if (result.success) {
      setPapers(papers.filter((p) => p.id !== id));
      toast.success('Paper deleted successfully!');
      if (selectedPaper?.id === id) {
        setSelectedPaper(null);
      }
    } else {
      toast.error('Failed to delete paper', {
        description: result.error,
      });
    }
    setLoading(false);
  };

  const getPreview = (content: string) => {
    // Get first sentence or first 150 characters
    const firstSentence = content.split(/[.!?]/)[0];
    const preview = firstSentence.length > 150
      ? content.substring(0, 150)
      : firstSentence;
    return preview.trim() + '...';
  };

  if (papers.length === 0) {
    return (
      <div className="text-center py-12">
        <FileText className="mx-auto h-12 w-12 text-gray-400" />
        <h3 className="mt-2 text-sm font-semibold text-gray-900">No papers yet</h3>
        <p className="mt-1 text-sm text-gray-500">
          Get started by creating your first paper.
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {papers.map((paper) => (
          <div
            key={paper.id}
            className="border rounded-lg p-6 hover:shadow-lg transition-all cursor-pointer bg-white"
            onClick={() => setSelectedPaper(paper)}
          >
            <h3 className="font-bold text-lg mb-2 line-clamp-2">{paper.title}</h3>
            <p className="text-sm text-gray-600 mb-4 line-clamp-2">
              {getPreview(paper.content)}
            </p>
            <div className="flex justify-between items-center text-xs text-gray-400">
              <span>
                {new Date(paper.createdAt).toLocaleDateString()}
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  handleDelete(paper.id);
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

      {/* View Paper Dialog */}
      <Dialog open={!!selectedPaper} onOpenChange={() => setSelectedPaper(null)}>
        <DialogContent className="max-w-4xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="text-2xl">{selectedPaper?.title}</DialogTitle>
            <DialogDescription>
              Created: {selectedPaper?.createdAt ? new Date(selectedPaper.createdAt).toLocaleString() : 'Unknown'}
              {' • '}
              {selectedPaper?.content ? selectedPaper.content.trim().split(/\s+/).filter(Boolean).length : 0} words
            </DialogDescription>
          </DialogHeader>
          <div className="mt-6 prose prose-sm max-w-none">
            <p className="whitespace-pre-wrap leading-relaxed">{selectedPaper?.content}</p>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
