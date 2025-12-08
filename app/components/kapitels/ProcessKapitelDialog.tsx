'use client';

import { useEffect, useState } from 'react';
import type { Kapitel } from '@/app/actions/kapitels';
import type { Quelle } from '@/app/actions/quellen';
import { createKapitelRun } from '@/app/actions/kapitels';
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
import { useAuth } from '@/app/components/providers/AuthProvider';
import { firestoreClient } from '@/app/lib/firebase/firestoreClient';
import { collection, onSnapshot } from 'firebase/firestore';

type AIModel = 'gpt-5-nano' | 'gpt-5-mini' | 'gpt-5.1';

interface ProcessKapitelDialogProps {
  kapitel: Kapitel;
  quellen: Quelle[];
}

type ResultState = Record<string, { content?: string; error?: string }>;

export function ProcessKapitelDialog({ kapitel, quellen }: ProcessKapitelDialogProps) {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [instruction, setInstruction] = useState('');
  const [model, setModel] = useState<AIModel>('gpt-5.1');
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<ResultState>({});
  const [runId, setRunId] = useState<string | null>(null);

  const handleProcess = async () => {
    if (quellen.length === 0) {
      toast.error('Bitte zuerst Quellen diesem Kapitel zuordnen.');
      return;
    }
    if (!instruction.trim()) {
      toast.error('Bitte Anweisungen eingeben.');
      return;
    }

    setLoading(true);
    setResults({});

    try {
      const token = Cookies.get('__session');
      if (!token) {
        toast.error('Authentifizierung erforderlich', {
          description: 'Bitte erneut anmelden.',
        });
        return;
      }

      const runResult = await createKapitelRun(kapitel.id, instruction.trim(), model);
      if (!runResult.success || !runResult.runId) {
        throw new Error(runResult.error || 'Run konnte nicht erstellt werden.');
      }

      const currentRunId = runResult.runId;
      setRunId(currentRunId);

      // initialize pending states
      const initial: ResultState = {};
      quellen.forEach((q) => {
        initial[q.id] = { content: undefined, error: undefined };
      });
      setResults(initial);

      const queue = [...quellen];
      const concurrency = Math.min(3, queue.length);

      const worker = async () => {
        while (queue.length > 0) {
          const nextQuelle = queue.shift();
          if (!nextQuelle) return;

          try {
            const response = await fetch('http://localhost:8000/api/process', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${token}`,
              },
              body: JSON.stringify({
                quelle_id: nextQuelle.id,
                kapitel_id: kapitel.id,
                run_id: currentRunId,
                user_input: instruction.trim(),
                model,
              }),
            });

            if (!response.ok) {
              const error = await response.json();
              throw new Error(error.detail || 'Fehler beim Verarbeiten');
            }

            // queued successfully
          } catch (err: any) {
            setResults((prev) => ({
              ...prev,
              [nextQuelle.id]: { error: err.message || 'Unbekannter Fehler' },
            }));
            console.error(`Error processing Quelle ${nextQuelle.id}:`, err);
          }
        }
      };

      await Promise.all(Array.from({ length: concurrency }, () => worker()));

      toast.info(`Kapitel "${kapitel.title}" in Warteschlange`, {
        description: 'Die Verarbeitung läuft. Dies kann einige Minuten dauern.',
      });
      setOpen(false);

    } catch (error: any) {
      console.error('Kapitel-Verarbeitung fehlgeschlagen:', error);
      toast.error('Verarbeitung fehlgeschlagen', {
        description: error.message || 'Ein Fehler ist aufgetreten',
      });
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    if (loading) return;
    setOpen(false);
    setResults({});
    setInstruction('');
    setRunId(null);
  };

  const runFinished =
    runId !== null &&
    quellen.length > 0 &&
    quellen.every((q) => results[q.id]?.content || results[q.id]?.error);

  // Listen for Firestore result updates when a run is active
  useEffect(() => {
    if (!user?.uid || !runId || !open) return;
    const resultsRef = collection(
      firestoreClient,
      'users',
      user.uid,
      'kapitels',
      kapitel.id,
      'runs',
      runId,
      'results'
    );

    const unsub = onSnapshot(resultsRef, (snapshot) => {
      snapshot.docChanges().forEach((change) => {
        const data: any = change.doc.data();
        setResults((prev) => ({
          ...prev,
          [change.doc.id]: {
            content:
              data.result_content ??
              data.resultContent ??
              data.content ??
              JSON.stringify(data),
          },
        }));
      });
    });

    return () => unsub();
  }, [user?.uid, runId, kapitel.id, open]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button onClick={() => setOpen(true)} variant="outline" size="sm" className="gap-2">
        <Sparkles className="h-4 w-4" />
        Kapitel verarbeiten
      </Button>

      <DialogContent className="max-w-5xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5" />
            Kapitel verarbeiten: {kapitel.title}
          </DialogTitle>
          <DialogDescription>
            Gleiche Anweisungen für alle {quellen.length} Quellen in diesem Kapitel anwenden.
          </DialogDescription>
        </DialogHeader>

        {runFinished ? (
          <div className="space-y-4 py-4">
            <div className="rounded-lg bg-muted p-3">
              <p className="text-sm text-muted-foreground">
                Run abgeschlossen. Ergebnisse sind gespeichert. Du kannst schließen oder neu laden.
              </p>
            </div>
            <div className="space-y-4">
              {quellen.map((quelle) => (
                <div key={quelle.id} className="border rounded-lg p-4 space-y-2">
                  <div className="flex items-center justify-between">
                    <h3 className="font-semibold text-sm">{quelle.title}</h3>
                    <span className="text-xs text-muted-foreground">Quelle</span>
                  </div>
                  <div className="rounded-lg bg-muted p-3">
                    <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed max-h-96 overflow-y-auto">
                      {results[quelle.id]?.content ||
                        results[quelle.id]?.error ||
                        'Noch kein Ergebnis'}
                    </pre>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-6 py-4">
            <div className="space-y-2">
              <Label htmlFor="model">Modell</Label>
              <Select value={model} onValueChange={(value) => setModel(value as AIModel)}>
                <SelectTrigger id="model">
                  <SelectValue placeholder="Modell wählen" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="gpt-5-nano">
                    <div className="flex flex-col items-start">
                      <span className="font-medium">GPT-5 Nano</span>
                      <span className="text-xs text-muted-foreground">Sehr schnell, günstig</span>
                    </div>
                  </SelectItem>
                  <SelectItem value="gpt-5-mini">
                    <div className="flex flex-col items-start">
                      <span className="font-medium">GPT-5 Mini</span>
                      <span className="text-xs text-muted-foreground">Balance</span>
                    </div>
                  </SelectItem>
                  <SelectItem value="gpt-5.1">
                    <div className="flex flex-col items-start">
                      <span className="font-medium">GPT-5.1</span>
                      <span className="text-xs text-muted-foreground">Standard (Default)</span>
                    </div>
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="instructions">Anweisungen</Label>
              <Textarea
                id="instructions"
                placeholder="Welche Anweisungen sollen für alle Quellen gelten?"
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                rows={10}
                className="resize-y"
                disabled={loading}
              />
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>{instruction.length} Zeichen</span>
                <span>{quellen.length} Quellen werden verarbeitet</span>
              </div>
            </div>
          </div>
        )}

        <DialogFooter>
          {runFinished ? (
            <>
              <Button variant="outline" onClick={() => window.location.reload()}>
                Neu laden
              </Button>
              <Button onClick={handleClose}>Schließen</Button>
            </>
          ) : (
            <>
              <Button
                type="button"
                variant="outline"
                onClick={handleClose}
                disabled={loading}
              >
                Abbrechen
              </Button>
              <Button
                onClick={handleProcess}
                disabled={loading || !instruction.trim() || quellen.length === 0}
              >
                {loading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Verarbeite {quellen.length} Quellen...
                  </>
                ) : (
                  <>
                    <Sparkles className="mr-2 h-4 w-4" />
                    Kapitel verarbeiten
                  </>
                )}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
