'use client';

import { useState } from 'react';
import type { Paper } from '@/app/actions/papers';
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import { toast } from 'sonner';
import { Sparkles, Loader2 } from 'lucide-react';
import Cookies from 'js-cookie';

type AIModel = 'gpt-5-nano' | 'gpt-5-mini' | 'gpt-5.1';

interface ProcessPapersDialogProps {
  papers: Paper[];
}

export function ProcessPapersDialog({ papers }: ProcessPapersDialogProps) {
  const [open, setOpen] = useState(false);
  const [selectedPaperIds, setSelectedPaperIds] = useState<string[]>([]);
  const [userInput, setUserInput] = useState('');
  const [model, setModel] = useState<AIModel>('gpt-5-mini');
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<Record<string, string>>({});

  const togglePaperSelection = (paperId: string) => {
    setSelectedPaperIds((prev) =>
      prev.includes(paperId)
        ? prev.filter((id) => id !== paperId)
        : [...prev, paperId]
    );
  };

  const selectAllPapers = () => {
    if (selectedPaperIds.length === papers.length) {
      setSelectedPaperIds([]);
    } else {
      setSelectedPaperIds(papers.map((p) => p.id));
    }
  };

  const handleProcess = async () => {
    if (selectedPaperIds.length === 0) {
      toast.error('Please select at least one paper');
      return;
    }

    if (!userInput.trim()) {
      toast.error('Please enter instructions for the AI');
      return;
    }

    setLoading(true);
    setResults({});

    try {
      const token = Cookies.get('__session');

      if (!token) {
        toast.error('Authentication required', {
          description: 'Please sign in again',
        });
        return;
      }

      // Process papers sequentially (can be made concurrent later)
      const newResults: Record<string, string> = {};

      for (const paperId of selectedPaperIds) {
        try {
          const response = await fetch('http://localhost:8000/api/process', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({
              paper_id: paperId,
              user_input: userInput.trim(),
              model: model,
            }),
          });

          if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Processing failed');
          }

          const data = await response.json();
          newResults[paperId] = data.result_content;

          toast.success(`Processed paper successfully!`, {
            description: `Used ${data.tokens_used} tokens with ${data.model_used}`,
          });
        } catch (error: any) {
          console.error(`Error processing paper ${paperId}:`, error);
          toast.error(`Failed to process paper`, {
            description: error.message || 'An error occurred',
          });
          newResults[paperId] = `Error: ${error.message}`;
        }
      }

      setResults(newResults);
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    if (!loading) {
      setOpen(false);
      setResults({});
      setSelectedPaperIds([]);
      setUserInput('');
    }
  };

  const selectedPapers = papers.filter((p) => selectedPaperIds.includes(p.id));

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="lg" className="gap-2">
          <Sparkles className="h-5 w-5" />
          Process Papers with AI
        </Button>
      </DialogTrigger>

      <DialogContent className="max-w-5xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5" />
            Process Papers with AI
          </DialogTitle>
          <DialogDescription>
            Select papers, choose a model, and provide instructions for AI processing
          </DialogDescription>
        </DialogHeader>

        {Object.keys(results).length === 0 ? (
          <div className="space-y-6 py-4">
            {/* Paper Selection */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <Label>Select Papers ({selectedPaperIds.length} selected)</Label>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={selectAllPapers}
                >
                  {selectedPaperIds.length === papers.length ? 'Deselect All' : 'Select All'}
                </Button>
              </div>

              <div className="border rounded-lg divide-y max-h-64 overflow-y-auto">
                {papers.length === 0 ? (
                  <div className="p-4 text-center text-sm text-muted-foreground">
                    No papers available. Create a paper first.
                  </div>
                ) : (
                  papers.map((paper) => (
                    <div
                      key={paper.id}
                      className="flex items-start gap-3 p-3 hover:bg-muted/50 cursor-pointer"
                      onClick={() => togglePaperSelection(paper.id)}
                    >
                      <Checkbox
                        checked={selectedPaperIds.includes(paper.id)}
                        onCheckedChange={() => togglePaperSelection(paper.id)}
                        className="mt-1"
                      />
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-sm line-clamp-1">{paper.title}</p>
                        <p className="text-xs text-muted-foreground line-clamp-2 mt-1">
                          {paper.content.substring(0, 100)}...
                        </p>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Model Selection */}
            <div className="space-y-2">
              <Label htmlFor="model">AI Model</Label>
              <Select value={model} onValueChange={(value) => setModel(value as AIModel)}>
                <SelectTrigger id="model">
                  <SelectValue placeholder="Select a model" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="gpt-5-nano">
                    <div className="flex flex-col items-start">
                      <span className="font-medium">GPT-5 Nano</span>
                      <span className="text-xs text-muted-foreground">Fast and cost-effective</span>
                    </div>
                  </SelectItem>
                  <SelectItem value="gpt-5-mini">
                    <div className="flex flex-col items-start">
                      <span className="font-medium">GPT-5 Mini</span>
                      <span className="text-xs text-muted-foreground">Balanced performance</span>
                    </div>
                  </SelectItem>
                  <SelectItem value="gpt-5.1">
                    <div className="flex flex-col items-start">
                      <span className="font-medium">GPT-5.1</span>
                      <span className="text-xs text-muted-foreground">Most capable model</span>
                    </div>
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Instructions */}
            <div className="space-y-2">
              <Label htmlFor="instructions">Instructions</Label>
              <Textarea
                id="instructions"
                placeholder="What would you like the AI to do with the selected paper(s)?

Examples:
• Summarize the main points in bullet format
• Create an executive summary
• Extract key findings and recommendations
• Analyze the methodology and conclusions
• Generate discussion questions
• Identify potential weaknesses or gaps"
                value={userInput}
                onChange={(e) => setUserInput(e.target.value)}
                rows={12}
                className="resize-y"
                disabled={loading}
              />
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>{userInput.length} characters</span>
                <span>{selectedPaperIds.length} paper(s) selected</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-4 py-4">
            <div className="space-y-4">
              {selectedPapers.map((paper) => (
                <div key={paper.id} className="border rounded-lg p-4 space-y-2">
                  <h3 className="font-semibold text-sm">{paper.title}</h3>
                  <div className="rounded-lg bg-muted p-3">
                    <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed max-h-96 overflow-y-auto">
                      {results[paper.id] || 'Processing...'}
                    </pre>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <DialogFooter>
          {Object.keys(results).length === 0 ? (
            <>
              <Button
                type="button"
                variant="outline"
                onClick={handleClose}
                disabled={loading}
              >
                Cancel
              </Button>
              <Button
                onClick={handleProcess}
                disabled={loading || !userInput.trim() || selectedPaperIds.length === 0}
              >
                {loading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Processing {selectedPaperIds.length} paper(s)...
                  </>
                ) : (
                  <>
                    <Sparkles className="mr-2 h-4 w-4" />
                    Process {selectedPaperIds.length} Paper(s)
                  </>
                )}
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="outline"
                onClick={() => {
                  setResults({});
                  setSelectedPaperIds([]);
                  setUserInput('');
                }}
              >
                Process Again
              </Button>
              <Button onClick={handleClose}>Done</Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
