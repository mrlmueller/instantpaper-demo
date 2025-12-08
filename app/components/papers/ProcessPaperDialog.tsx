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
import { toast } from 'sonner';
import { Sparkles, Loader2 } from 'lucide-react';
import Cookies from 'js-cookie';

type AIModel = 'gpt-5-nano' | 'gpt-5-mini' | 'gpt-5.1';

interface ProcessPaperDialogProps {
  paper: Paper;
  trigger?: React.ReactNode;
}

export function ProcessPaperDialog({ paper, trigger }: ProcessPaperDialogProps) {
  const [open, setOpen] = useState(false);
  const [userInput, setUserInput] = useState('');
  const [model, setModel] = useState<AIModel>('gpt-5-mini');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const handleProcess = async () => {
    if (!userInput.trim()) {
      toast.error('Please enter instructions for the AI');
      return;
    }

    setLoading(true);
    setResult(null);

    try {
      // Get Firebase token from cookie
      const token = Cookies.get('__session');

      if (!token) {
        toast.error('Authentication required', {
          description: 'Please sign in again',
        });
        return;
      }

      // Call FastAPI backend
      const response = await fetch('http://localhost:8000/api/process', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          paper_id: paper.id,
          user_input: userInput.trim(),
          model: model,
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Processing failed');
      }

      const data = await response.json();

      setResult(data.result_content);
      toast.success('Paper processed successfully!', {
        description: `Used ${data.tokens_used} tokens with ${data.model_used}`,
      });

    } catch (error: any) {
      console.error('Error processing paper:', error);
      toast.error('Failed to process paper', {
        description: error.message || 'An error occurred',
      });
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    if (!loading) {
      setOpen(false);
      setResult(null);
      setUserInput('');
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {trigger ? (
        <div onClick={() => setOpen(true)}>{trigger}</div>
      ) : (
        <Button onClick={() => setOpen(true)} variant="outline" size="sm">
          <Sparkles className="mr-2 h-4 w-4" />
          Process with AI
        </Button>
      )}

      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5" />
            Process: {paper.title}
          </DialogTitle>
          <DialogDescription>
            Use AI to analyze, summarize, or transform your paper content
          </DialogDescription>
        </DialogHeader>

        {!result ? (
          <div className="space-y-6 py-4">
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

            <div className="space-y-2">
              <Label htmlFor="instructions">Instructions</Label>
              <Textarea
                id="instructions"
                placeholder="What would you like the AI to do with this paper?

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
                <span>Paper: {paper.content.length} characters</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-4 py-4">
            <div className="rounded-lg bg-muted p-4">
              <h3 className="font-semibold mb-2">AI Result</h3>
              <div className="prose prose-sm max-w-none">
                <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">
                  {result}
                </pre>
              </div>
            </div>
          </div>
        )}

        <DialogFooter>
          {!result ? (
            <>
              <Button
                type="button"
                variant="outline"
                onClick={handleClose}
                disabled={loading}
              >
                Cancel
              </Button>
              <Button onClick={handleProcess} disabled={loading || !userInput.trim()}>
                {loading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Processing...
                  </>
                ) : (
                  <>
                    <Sparkles className="mr-2 h-4 w-4" />
                    Process Paper
                  </>
                )}
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="outline"
                onClick={() => {
                  setResult(null);
                  setUserInput('');
                }}
              >
                Process Again
              </Button>
              <Button onClick={handleClose}>
                Done
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
