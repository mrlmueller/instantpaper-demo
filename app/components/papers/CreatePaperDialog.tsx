'use client';

import { useState } from 'react';
import { createPaper } from '@/app/actions/papers';
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

export function CreatePaperDialog() {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!title.trim()) {
      toast.error('Title is required');
      return;
    }

    if (!content.trim()) {
      toast.error('Content is required');
      return;
    }

    setLoading(true);
    const result = await createPaper(title.trim(), content.trim());

    if (result.success) {
      toast.success('Paper created successfully!');
      setTitle('');
      setContent('');
      setOpen(false);
      // Refresh the page to show the new paper
      window.location.reload();
    } else {
      toast.error('Failed to create paper', {
        description: result.error,
      });
    }
    setLoading(false);
  };

  const wordCount = content.trim().split(/\s+/).filter(Boolean).length;
  const charCount = content.length;

  return (
    <>
      <Button onClick={() => setOpen(true)} size="lg">
        <Plus className="mr-2 h-5 w-5" />
        New Paper
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Create New Paper</DialogTitle>
            <DialogDescription>
              Write your paper below. Perfect for long-form content (2000-3000 words).
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={handleSubmit} className="space-y-6">
            <div className="space-y-2">
              <Label htmlFor="title">Title</Label>
              <Input
                id="title"
                placeholder="Enter paper title..."
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                disabled={loading}
                required
              />
            </div>

            <div className="space-y-2">
              <div className="flex justify-between items-center">
                <Label htmlFor="content">Content</Label>
                <span className="text-sm text-gray-500">
                  {wordCount} words · {charCount} characters
                </span>
              </div>
              <Textarea
                id="content"
                placeholder="Start writing your paper here...

Perfect for long-form content. Write as much as you need - this field supports 2000-3000 words easily.

Tips:
- Take your time writing
- Use paragraphs to organize your thoughts
- This textarea will automatically expand as you type"
                value={content}
                onChange={(e) => setContent(e.target.value)}
                disabled={loading}
                required
                rows={20}
                className="resize-y min-h-[400px] font-mono text-sm"
              />
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setOpen(false)}
                disabled={loading}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={loading}>
                {loading ? 'Creating...' : 'Create Paper'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
