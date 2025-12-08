'use client';

import { useState } from 'react';
import { createPaper, deletePaper } from '@/app/actions/papers';
import type { Paper } from '@/app/actions/papers';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';

export function TestPapers({ initialPapers }: { initialPapers: Paper[] }) {
  const [papers, setPapers] = useState(initialPapers);
  const [loading, setLoading] = useState(false);
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null);

  const handleCreateTest = async () => {
    setLoading(true);
    const result = await createPaper(
      'Test Paper ' + Date.now(),
      'This is a test paper content. '.repeat(100) // ~300 words
    );
    if (result.success) {
      toast.success('Paper created successfully!', {
        description: 'Refresh the page to see your new paper.',
      });
    } else {
      toast.error('Failed to create paper', {
        description: result.error,
      });
    }
    setLoading(false);
  };

  const handleDelete = async (id: string) => {
    setLoading(true);
    const result = await deletePaper(id);
    if (result.success) {
      setPapers(papers.filter((p) => p.id !== id));
      toast.success('Paper deleted successfully!');
    } else {
      toast.error('Failed to delete paper', {
        description: result.error,
      });
    }
    setLoading(false);
  };

  return (
    <>
      <div className="mt-8 p-6 bg-white border rounded-lg">
        <h2 className="text-xl font-bold mb-4">Test Paper Operations</h2>

        <Button onClick={handleCreateTest} disabled={loading} className="mb-4">
          {loading ? 'Creating...' : 'Create Test Paper'}
        </Button>

        <div className="space-y-4">
          <h3 className="font-semibold">Your Papers ({papers.length}):</h3>
          {papers.length === 0 ? (
            <p className="text-gray-500">No papers yet. Create one to test!</p>
          ) : (
            papers.map((paper) => (
              <div
                key={paper.id}
                className="p-4 border rounded hover:bg-gray-50 cursor-pointer transition"
                onClick={() => setSelectedPaper(paper)}
              >
                <h4 className="font-bold">{paper.title}</h4>
                <p className="text-sm text-gray-600 mt-1">
                  {paper.content.substring(0, 100)}...
                </p>
                <p className="text-xs text-gray-400 mt-2">ID: {paper.id}</p>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDelete(paper.id);
                  }}
                  disabled={loading}
                  className="mt-2"
                >
                  Delete
                </Button>
              </div>
            ))
          )}
        </div>
      </div>

      {/* View Paper Dialog */}
      <Dialog open={!!selectedPaper} onOpenChange={() => setSelectedPaper(null)}>
        <DialogContent className="max-w-4xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{selectedPaper?.title}</DialogTitle>
            <DialogDescription>
              Created: {selectedPaper?.createdAt ? new Date(selectedPaper.createdAt).toLocaleString() : 'Unknown'}
            </DialogDescription>
          </DialogHeader>
          <div className="mt-4">
            <p className="whitespace-pre-wrap text-sm">{selectedPaper?.content}</p>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
