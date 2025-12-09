'use client';

import { useState, useCallback, useEffect } from 'react';
import { KapitelNavigator } from './KapitelNavigator';
import { KapitelWorkspace } from './KapitelWorkspace';
import { ProjektHeader } from './ProjektHeader';
import { QuellenPanel } from './QuellenPanel';
import { TextViewerModal } from './TextViewerModal';
import { ProcessingDialog } from './ProcessingDialog';
import { DeleteConfirmDialog } from './DeleteConfirmDialog';
import { DashboardSkeleton } from './DashboardSkeleton';
import { QuellenPanelSkeleton } from './QuellenPanelSkeleton';
import { toast } from 'sonner';

import type { Quelle, Kapitel, Run, ProcessingSettings, Projekt } from '@/app/types/ui';
import {
  transformQuelleToUI,
  transformKapitelToUI,
  transformRunToUI,
  createQuellenMap,
} from '@/app/lib/transformers/ui-data';

// Import Server Actions
import {
  createQuelle,
  deleteQuelle as deleteQuelleAction,
  type Quelle as FirebaseQuelle,
} from '@/app/actions/quellen';
import {
  createKapitel,
  updateKapitelQuellen,
  deleteKapitel as deleteKapitelAction,
  updateKapitelTitle,
  createKapitelRun,
  type KapitelRun as FirebaseKapitelRun,
  type Kapitel as FirebaseKapitel,
} from '@/app/actions/kapitels';

// Firebase real-time
import { useAuth } from '@/app/components/providers/AuthProvider';
import { firebaseApp } from '@/app/lib/firebase/config';
import {
  getFirestore,
  collection,
  onSnapshot,
  query,
  orderBy,
  type Unsubscribe,
  doc,
  updateDoc,
  serverTimestamp,
  addDoc,
  deleteDoc,
} from 'firebase/firestore';
import Cookies from 'js-cookie';

const API_BASE_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://localhost:8000';

interface DashboardProps {
  initialKapitels: FirebaseKapitel[];
  initialQuellen: FirebaseQuelle[];
}

export function Dashboard({ initialKapitels, initialQuellen }: DashboardProps) {
  const { user } = useAuth();
  // Start with skeleton to avoid empty flash before data appears
  const [isLoading, setIsLoading] = useState(true);
  const [isQuellenLoading, setIsQuellenLoading] = useState(false);

  // Project state (single project for now)
  const [projekt] = useState<Projekt>({
    id: '1',
    name: 'Meine Arbeit',
    createdAt: new Date(),
  });

  // Transform initial data
  const [quellen, setQuellen] = useState<Quelle[]>(
    initialQuellen.map((q) => transformQuelleToUI(q, projekt.id))
  );
  const [kapiteln, setKapiteln] = useState<Kapitel[]>(
    initialKapitels.map((k) => transformKapitelToUI(k, projekt.id))
  );

  // UI state
  const initialActiveKapitelId = kapiteln[0]?.id || '';
  const [activeKapitelId, setActiveKapitelId] = useState(initialActiveKapitelId);
  const activeKapitel = kapiteln.find((k) => k.id === activeKapitelId);

  const initialRunsForActive =
    initialKapitels.find((k) => k.id === initialActiveKapitelId)?.runs || [];
  const [fbRuns, setFbRuns] = useState<FirebaseKapitelRun[]>(initialRunsForActive);
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const selectedRun = runs.find((r) => r.id === selectedRunId);

  const [showQuellenPanel, setShowQuellenPanel] = useState(false);
  const [textViewerContent, setTextViewerContent] = useState<{
    title: string;
    text: string;
  } | null>(null);
  const [processingDialogOpen, setProcessingDialogOpen] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<{
    type: 'quelle' | 'kapitel';
    id: string;
    name: string;
  } | null>(null);

  const persistKapitelQuellenClient = useCallback(async (kapitelId: string, quelleIds: string[]) => {
    if (!user?.uid) throw new Error('Kein Nutzer angemeldet');
    const db = getFirestore(firebaseApp);
    const kapitelRef = doc(db, 'users', user.uid, 'kapitels', kapitelId);
    await updateDoc(kapitelRef, {
      quelleIds,
      updatedAt: serverTimestamp(),
    });
  }, [user?.uid]);

  const createKapitelClient = useCallback(async (title: string, nummer: string, parentId: string | null = null) => {
    if (!user?.uid) throw new Error('Kein Nutzer angemeldet');
    const db = getFirestore(firebaseApp);
    const kapitelsRef = collection(db, 'users', user.uid, 'kapitels');
    const docRef = await addDoc(kapitelsRef, {
      title,
      nummer,
      quelleIds: [],
      parentId,
      order: Date.now(),
      createdAt: serverTimestamp(),
    });
    return docRef.id;
  }, [user?.uid]);

  const updateKapitelTitleClient = useCallback(async (kapitelId: string, title: string, nummer: string) => {
    if (!user?.uid) throw new Error('Kein Nutzer angemeldet');
    const db = getFirestore(firebaseApp);
    const kapitelRef = doc(db, 'users', user.uid, 'kapitels', kapitelId);
    await updateDoc(kapitelRef, {
      title,
      nummer,
      updatedAt: serverTimestamp(),
    });
  }, [user?.uid]);

  const deleteKapitelClient = useCallback(async (kapitelId: string) => {
    if (!user?.uid) throw new Error('Kein Nutzer angemeldet');
    const db = getFirestore(firebaseApp);
    const kapitelRef = doc(db, 'users', user.uid, 'kapitels', kapitelId);
    await deleteDoc(kapitelRef);
  }, [user?.uid]);

  // When the active Kapitel changes, seed runs from initial data while real-time listeners attach
  useEffect(() => {
    if (!activeKapitelId) {
      setFbRuns([]);
      setRuns([]);
      setSelectedRunId(null);
      return;
    }

    const initialKapitel = initialKapitels.find((k) => k.id === activeKapitelId);
    setFbRuns(initialKapitel?.runs || []);
    setSelectedRunId(null);
  }, [activeKapitelId, initialKapitels]);

  // Real-time updates for runs, results, and combined content of the active Kapitel
  useEffect(() => {
    if (!user?.uid || !activeKapitelId) {
      setFbRuns([]);
      setRuns([]);
      setSelectedRunId(null);
      return;
    }

    const db = getFirestore(firebaseApp);
    const runsRef = collection(db, 'users', user.uid, 'kapitels', activeKapitelId, 'runs');
    const q = query(runsRef, orderBy('index', 'desc'));

    let runLevelUnsubs: Unsubscribe[] = [];

    const unsubscribeRuns = onSnapshot(
      q,
      (snapshot) => {
        // Reset existing run-level listeners to avoid duplicates when the run list changes
        runLevelUnsubs.forEach((u) => u());
        runLevelUnsubs = [];

        setFbRuns((prev) => {
          const prevMap = new Map(prev.map((run) => [run.id, run]));
          const baseRuns: FirebaseKapitelRun[] = snapshot.docs.map((doc) => {
            const data: any = doc.data();
            const existing = prevMap.get(doc.id);
            return {
              id: doc.id,
              index: data.index || 0,
              instruction: data.instruction || '',
              model: data.model || '',
              createdAt:
                data.createdAt?.toDate?.()?.toISOString() ||
                data.created_at?.toDate?.()?.toISOString() ||
                new Date().toISOString(),
              promptTemplateId: data.promptTemplateId,
              promptPayload: data.promptPayload,
              autoCombine: data.autoCombine ?? false,
              results: existing?.results || [],
              combined: existing?.combined || null,
              ueberschrift: data.ueberschrift || existing?.ueberschrift || '',
              thema: data.thema || data.instruction || existing?.thema || '',
            } as FirebaseKapitelRun;
          });
          return baseRuns;
        });

        // Subscribe to result/combined updates for each run
        snapshot.docs.forEach((runDoc) => {
          const resultsRef = collection(
            db,
            'users',
            user.uid,
            'kapitels',
            activeKapitelId,
            'runs',
            runDoc.id,
            'results'
          );
          const resultsUnsub = onSnapshot(resultsRef, (resSnapshot) => {
            const results = resSnapshot.docs.map((resDoc) => {
              const resData: any = resDoc.data();
              return {
                quelleId: resDoc.id,
                resultContent: resData.result_content ?? resData.resultContent ?? '',
                hasContent: resData.has_content ?? resData.hasContent ?? true,
                modelUsed: resData.model_used ?? resData.modelUsed ?? '',
                tokensUsed: resData.tokens_used ?? resData.tokensUsed ?? 0,
                inputTokens: resData.input_tokens ?? resData.inputTokens ?? 0,
                cachedInputTokens: resData.cached_input_tokens ?? resData.cachedInputTokens ?? 0,
                outputTokens: resData.output_tokens ?? resData.outputTokens ?? 0,
                reasoningTokens: resData.reasoning_tokens ?? resData.reasoningTokens ?? 0,
                cost: resData.cost ?? 0,
                createdAt:
                  resData.created_at?.toDate?.()?.toISOString() ||
                  resData.createdAt?.toDate?.()?.toISOString() ||
                  new Date().toISOString(),
              };
            });

            setFbRuns((prev) =>
              prev.map((run) => (run.id === runDoc.id ? { ...run, results } : run))
            );
          });
          runLevelUnsubs.push(resultsUnsub);

          const combinedRef = collection(
            db,
            'users',
            user.uid,
            'kapitels',
            activeKapitelId,
            'runs',
            runDoc.id,
            'combined'
          );
          const combinedUnsub = onSnapshot(combinedRef, (combinedSnap) => {
            let combined: any = null;
            if (!combinedSnap.empty) {
              const doc = combinedSnap.docs[0];
              const data: any = doc.data();
              combined = {
                id: doc.id,
                combinedContent: data.combined_content ?? data.combinedContent ?? '',
                sourceQuelleIds: data.source_quelle_ids ?? data.sourceQuelleIds ?? [],
                heading: data.heading ?? '',
                topic: data.topic ?? '',
                modelUsed: data.model_used ?? data.modelUsed ?? '',
                tokensUsed: data.tokens_used ?? data.tokensUsed ?? 0,
                inputTokens: data.input_tokens ?? data.inputTokens ?? 0,
                cachedInputTokens: data.cached_input_tokens ?? data.cachedInputTokens ?? 0,
                outputTokens: data.output_tokens ?? data.outputTokens ?? 0,
                reasoningTokens: data.reasoning_tokens ?? data.reasoningTokens ?? 0,
                cost: data.cost ?? 0,
                createdAt:
                  data.created_at?.toDate?.()?.toISOString() ||
                  data.createdAt?.toDate?.()?.toISOString() ||
                  new Date().toISOString(),
              };
            }

            setFbRuns((prev) =>
              prev.map((run) => (run.id === runDoc.id ? { ...run, combined } : run))
            );
          });
          runLevelUnsubs.push(combinedUnsub);
        });
      },
      (error) => {
        console.error('Error listening to runs:', error);
      }
    );

    return () => {
      unsubscribeRuns();
      runLevelUnsubs.forEach((u) => u());
    };
  }, [user?.uid, activeKapitelId]);

  // hide initial skeleton once first client render completes
  useEffect(() => {
    setIsLoading(false);
  }, []);

  // Transform Firestore run data to UI runs, keep selection and Kapitel status in sync
  useEffect(() => {
    if (!activeKapitelId) {
      setRuns([]);
      setSelectedRunId(null);
      return;
    }

    const quellenMap = createQuellenMap(quellen);
    const assignedQuelleIds = activeKapitel?.assignedQuellenIds || [];

    // Deduplicate runs by id to avoid duplicate keys in run select
    const uniqueFbRuns = Array.from(
      fbRuns.reduce((map, run) => (map.has(run.id) ? map : map.set(run.id, run)), new Map<string, FirebaseKapitelRun>())
        .values()
    );

    const uiRuns = uniqueFbRuns.map((fbRun) => {
      const uiRun = transformRunToUI(fbRun, activeKapitelId, quellenMap);
      const existingIds = new Set(uiRun.quellenErgebnisse.map((r) => r.quelleId));
      const waitingResults = assignedQuelleIds
        .filter((id) => !existingIds.has(id))
        .map((id) => ({
          id,
          quelleId: id,
          quelleName: quellenMap.get(id) || '',
          text: '',
          status: 'waiting' as const,
          cost: 0,
        }));

      return {
        ...uiRun,
        quellenErgebnisse: [...uiRun.quellenErgebnisse, ...waitingResults],
      };
    });

    setRuns(uiRuns);

    if (uiRuns.length === 0) {
      setSelectedRunId(null);
    } else if (!selectedRunId || !uiRuns.some((run) => run.id === selectedRunId)) {
      setSelectedRunId(uiRuns[0].id);
    }

    // update status for the active Kapitel based on its latest run
    const nextStatus = deriveKapitelStatus(fbRuns);
    setKapiteln((prev) =>
      prev.map((k) => (k.id === activeKapitelId ? { ...k, status: nextStatus } : k))
    );
  }, [fbRuns, quellen, activeKapitelId, activeKapitel?.assignedQuellenIds, selectedRunId]);

  // Handlers
  const handleAddQuelle = useCallback(
    async (name: string, text: string) => {
      const result = await createQuelle(name, text);
      if (result.success) {
        toast.success('Quelle hinzugefügt', {
          description: `"${name}" wurde erfolgreich erstellt.`,
        });
        // Optimistically update UI
        const newQuelle: Quelle = {
          id: result.id!,
          name,
          text,
          projektId: projekt.id,
          createdAt: new Date(),
        };
        setQuellen((prev) => [...prev, newQuelle]);
      } else {
        toast.error('Fehler', { description: result.error });
      }
    },
    [projekt.id]
  );

  const handleDeleteQuelle = useCallback(async (id: string) => {
    const result = await deleteQuelleAction(id);
    if (result.success) {
      setQuellen((prev) => prev.filter((q) => q.id !== id));
      // Also remove from all kapitels
      setKapiteln((prev) =>
        prev.map((k) => ({
          ...k,
          assignedQuellenIds: k.assignedQuellenIds.filter((qid) => qid !== id),
        }))
      );
      setDeleteConfirm(null);
      toast.success('Quelle gelöscht');
    } else {
      toast.error('Fehler', { description: result.error });
    }
  }, []);

  const handleAssignQuelle = useCallback(
    async (quelleId: string) => {
      if (!activeKapitelId) return;
      const kapitel = kapiteln.find((k) => k.id === activeKapitelId);
      if (!kapitel) return;

      const prevQuelleIds = kapitel.assignedQuellenIds;
      const newQuelleIds = [...prevQuelleIds, quelleId];

      // Optimistic update for snappier UI
      setKapiteln((prev) =>
        prev.map((k) => (k.id === activeKapitelId ? { ...k, assignedQuellenIds: newQuelleIds } : k))
      );

      try {
        await persistKapitelQuellenClient(activeKapitelId, newQuelleIds);
      } catch (clientErr) {
        // Fallback to server action
        const result = await updateKapitelQuellen(activeKapitelId, newQuelleIds);
        if (!result.success) {
          setKapiteln((prev) =>
            prev.map((k) => (k.id === activeKapitelId ? { ...k, assignedQuellenIds: prevQuelleIds } : k))
          );
          toast.error('Fehler', { description: result.error });
        }
      }
    },
    [activeKapitelId, kapiteln, persistKapitelQuellenClient]
  );

  const handleUnassignQuelle = useCallback(
    async (quelleId: string) => {
      if (!activeKapitelId) return;
      const kapitel = kapiteln.find((k) => k.id === activeKapitelId);
      if (!kapitel) return;

      const prevQuelleIds = kapitel.assignedQuellenIds;
      const newQuelleIds = prevQuelleIds.filter((id) => id !== quelleId);

      // Optimistic update for snappier UI
      setKapiteln((prev) =>
        prev.map((k) => (k.id === activeKapitelId ? { ...k, assignedQuellenIds: newQuelleIds } : k))
      );

      try {
        await persistKapitelQuellenClient(activeKapitelId, newQuelleIds);
      } catch (clientErr) {
        const result = await updateKapitelQuellen(activeKapitelId, newQuelleIds);
        if (!result.success) {
          setKapiteln((prev) =>
            prev.map((k) => (k.id === activeKapitelId ? { ...k, assignedQuellenIds: prevQuelleIds } : k))
          );
          toast.error('Fehler', { description: result.error });
        }
      }
    },
    [activeKapitelId, kapiteln, persistKapitelQuellenClient]
  );

  const handleAddKapitel = useCallback(async (title: string, nummer: string) => {
    const tempId = `temp-${Date.now()}`;
    const newKapitel: Kapitel = {
      id: tempId,
      title,
      nummer,
      status: 'nicht-verarbeitet',
      order: Date.now(),
      projektId: projekt.id,
      assignedQuellenIds: [],
    };

    // Optimistic UI update
    setKapiteln((prev) => [newKapitel, ...prev]);
    setActiveKapitelId(tempId);

    try {
      const newId = await createKapitelClient(title, nummer, null);
      setKapiteln((prev) =>
        prev.map((k) => (k.id === tempId ? { ...k, id: newId } : k))
      );
      setActiveKapitelId(newId);
      toast.success('Kapitel erstellt', {
        description: `"${nummer} ${title}" wurde hinzugefügt.`,
      });
    } catch (clientErr) {
      // Fallback to server action
      const result = await createKapitel(title, [], null, nummer);
      if (result.success && result.id) {
        setKapiteln((prev) =>
          prev.map((k) => (k.id === tempId ? { ...k, id: result.id! } : k))
        );
        setActiveKapitelId(result.id);
        toast.success('Kapitel erstellt', {
          description: `"${nummer} ${title}" wurde hinzugefügt.`,
        });
      } else {
        // Revert on failure
        setKapiteln((prev) => prev.filter((k) => k.id !== tempId));
        setActiveKapitelId((prev) => (prev === tempId ? kapiteln[0]?.id || '' : prev));
        toast.error('Fehler', { description: result.error || (clientErr as Error).message });
      }
    }
  }, [createKapitelClient, kapiteln, projekt.id]);

  const handleDeleteKapitel = useCallback(
    async (id: string) => {
      const prevKapiteln = kapiteln;
      const remaining = kapiteln.filter((k) => k.id !== id);
      setKapiteln(remaining);
      if (activeKapitelId === id) {
        setActiveKapitelId(remaining[0]?.id || '');
      }
      setDeleteConfirm(null);

      try {
        await deleteKapitelClient(id);
        toast.success('Kapitel gelöscht');
      } catch (clientErr) {
        const result = await deleteKapitelAction(id);
        if (result.success) {
          toast.success('Kapitel gelöscht');
        } else {
          // Revert on failure
          setKapiteln(prevKapiteln);
          setActiveKapitelId(activeKapitelId);
          toast.error('Fehler', { description: result.error || (clientErr as Error).message });
        }
      }
    },
    [activeKapitelId, kapiteln, deleteKapitelClient]
  );

  const handleEditKapitel = useCallback(async (id: string, title: string, nummer: string) => {
    const prevKapiteln = kapiteln;
    setKapiteln((prev) => prev.map((k) => (k.id === id ? { ...k, title, nummer } : k)));

    try {
      await updateKapitelTitleClient(id, title, nummer);
      toast.success('Kapitel aktualisiert', {
        description: `"${nummer} ${title}" wurde gespeichert.`,
      });
    } catch (clientErr) {
      const result = await updateKapitelTitle(id, title, nummer);
      if (!result.success) {
        setKapiteln(prevKapiteln);
        toast.error('Fehler', { description: result.error || (clientErr as Error).message });
      } else {
        toast.success('Kapitel aktualisiert', {
          description: `"${nummer} ${title}" wurde gespeichert.`,
        });
      }
    }
  }, [kapiteln, updateKapitelTitleClient]);

  const handleProcess = useCallback(
    async (settings: ProcessingSettings) => {
      if (!activeKapitel) return;

      const assignedQuellen = quellen.filter((q) => activeKapitel.assignedQuellenIds.includes(q.id));
      if (assignedQuellen.length === 0) {
        toast.error('Keine Quellen', {
          description: 'Füge zuerst Quellen zu diesem Kapitel hinzu.',
        });
        return;
      }

      if (!settings.ueberschrift.trim() || !settings.thema.trim()) {
        toast.error('Bitte Überschrift und Thema angeben.');
        return;
      }

      const token = Cookies.get('__session');
      if (!token) {
        toast.error('Authentifizierung erforderlich', {
          description: 'Bitte melde dich erneut an.',
        });
        return;
      }

      const prompt = buildPrompt(settings.ueberschrift.trim(), settings.thema.trim(), settings.grundlegendeInfos);

      toast.loading('Verarbeitung gestartet', {
        description: `"${settings.ueberschrift}" wird mit ${assignedQuellen.length} Quellen verarbeitet...`,
        id: 'processing',
      });

      try {
        const result = await createKapitelRun(activeKapitelId, prompt, settings.model, {
          autoCombine: settings.directCombine,
          promptTemplateId: 'wissenschaftlicher_absatz_v1',
          promptPayload: {
            heading: settings.ueberschrift.trim(),
            topic: settings.thema.trim(),
          },
          grundlegendeInformationen: settings.grundlegendeInfos?.trim() || undefined,
          ueberschrift: settings.ueberschrift.trim(),
          thema: settings.thema.trim(),
        });

        if (!result.success || !result.runId) {
          throw new Error(result.error || 'Run konnte nicht erstellt werden.');
        }

        // Optimistically show the new run while Firestore listeners update
        setFbRuns((prev) => {
          if (prev.some((r) => r.id === result.runId)) return prev;
          return [
            {
              id: result.runId!,
              index: result.index ?? (prev[0]?.index || 0) + 1,
              instruction: prompt,
              model: settings.model,
              createdAt: new Date().toISOString(),
              promptTemplateId: 'wissenschaftlicher_absatz_v1',
              promptPayload: {
                heading: settings.ueberschrift.trim(),
                topic: settings.thema.trim(),
              },
              autoCombine: settings.directCombine,
              results: [],
              combined: null,
              ueberschrift: settings.ueberschrift.trim(),
              thema: settings.thema.trim(),
            },
            ...prev,
          ];
        });
        setSelectedRunId(result.runId);
        setProcessingDialogOpen(false);

        // Queue processing for all assigned Quellen (mirrors previous implementation)
        const queue = [...assignedQuellen];
        const concurrency = Math.min(3, queue.length || 1);

        const worker = async () => {
          while (queue.length > 0) {
            const nextQuelle = queue.shift();
            if (!nextQuelle) return;
            try {
              const response = await fetch(`${API_BASE_URL}/api/process`, {
                method: 'POST',
                headers: {
                  'Content-Type': 'application/json',
                  Authorization: `Bearer ${token}`,
                },
                body: JSON.stringify({
                  quelle_id: nextQuelle.id,
                  kapitel_id: activeKapitelId,
                  run_id: result.runId,
                  user_input: prompt,
                  model: settings.model,
                }),
              });

              if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.detail || 'Fehler beim Verarbeiten');
              }
            } catch (err: any) {
              console.error(`Error processing Quelle ${nextQuelle.id}:`, err);
              toast.error('Fehler bei einer Quelle', {
                description: err.message || 'Unbekannter Fehler beim Verarbeiten der Quelle',
              });
            }
          }
        };

        await Promise.all(Array.from({ length: concurrency }, () => worker()));

        toast.success('Run erstellt', {
          description: 'Die Verarbeitung wurde gestartet...',
          id: 'processing',
        });
      } catch (error: any) {
        console.error('Fehler beim Starten der Verarbeitung:', error);
        toast.error('Fehler beim Erstellen des Runs', {
          description: error.message || 'Ein Fehler ist aufgetreten.',
          id: 'processing',
        });
      }
    },
    [activeKapitelId, activeKapitel, quellen]
  );

  const handleCombineTexts = useCallback(async () => {
    if (!activeKapitelId || !selectedRun) {
      toast.error('Kein Run ausgewählt');
      return;
    }

    const readyResults =
      selectedRun.quellenErgebnisse?.filter((r) => r.status !== 'waiting' && r.text?.trim()) || [];
    if (readyResults.length < 2) {
      toast.error('Zu wenige Texte zum Kombinieren', {
        description: 'Mindestens zwei Quellen müssen ein Ergebnis haben.',
      });
      return;
    }

    const token = Cookies.get('__session');
    if (!token) {
      toast.error('Authentifizierung erforderlich', {
        description: 'Bitte melde dich erneut an.',
      });
      return;
    }

    toast.loading('Texte kombinieren', {
      description: 'Die Texte werden kombiniert...',
      id: 'combine',
    });

    try {
      const response = await fetch(`${API_BASE_URL}/api/combine-run`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          kapitel_id: activeKapitelId,
          run_id: selectedRun.id,
        }),
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || 'Fehler beim Kombinieren');
      }

      toast.success('Kombination gestartet', {
        description: 'Die Texte werden nun zusammengeführt.',
        id: 'combine',
      });
    } catch (err: any) {
      console.error('Fehler beim Kombinieren:', err);
      toast.error('Combine fehlgeschlagen', {
        description: err.message || 'Unbekannter Fehler beim Kombinieren',
        id: 'combine',
      });
    }
  }, [activeKapitelId, selectedRun]);

  const handleToggleQuellenPanel = useCallback(() => {
    if (!showQuellenPanel) {
      setIsQuellenLoading(true);
      setShowQuellenPanel(true);
      setTimeout(() => {
        setIsQuellenLoading(false);
      }, 300);
    } else {
      setShowQuellenPanel(false);
    }
  }, [showQuellenPanel]);

  if (isLoading || !projekt) {
    return <DashboardSkeleton />;
  }

  const assignedQuellen = quellen.filter((q) => activeKapitel?.assignedQuellenIds.includes(q.id));

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Left Navigator */}
      <div className="w-64 border-r border-border bg-sidebar flex flex-col">
        <ProjektHeader projekt={projekt} projekte={[projekt]} />
        <KapitelNavigator
          kapiteln={kapiteln}
          activeKapitelId={activeKapitelId}
          onKapitelSelect={setActiveKapitelId}
          onAddKapitel={handleAddKapitel}
          onDeleteKapitel={(id, name) => setDeleteConfirm({ type: 'kapitel', id, name })}
          onEditKapitel={handleEditKapitel}
        />
      </div>

      {/* Main Workspace */}
      <div className="flex-1 overflow-hidden flex">
        <div className="flex-1 overflow-hidden">
          {activeKapitel ? (
            <KapitelWorkspace
              kapitel={activeKapitel}
              assignedQuellen={assignedQuellen}
              runs={runs}
              selectedRun={selectedRun}
              onSelectRun={setSelectedRunId}
              onOpenTextViewer={setTextViewerContent}
              onOpenProcessing={() => setProcessingDialogOpen(true)}
              onCombineTexts={handleCombineTexts}
              onToggleQuellenPanel={handleToggleQuellenPanel}
            />
          ) : (
            <div className="h-full flex items-center justify-center">
              <div className="text-center">
                <p className="text-muted-foreground">Wähle ein Kapitel aus oder erstelle ein neues.</p>
              </div>
            </div>
          )}
        </div>

        {showQuellenPanel &&
          activeKapitel &&
          (isQuellenLoading ? (
            <QuellenPanelSkeleton />
          ) : (
            <QuellenPanel
              quellen={quellen}
              assignedQuellenIds={activeKapitel.assignedQuellenIds}
              onClose={() => setShowQuellenPanel(false)}
              onAddQuelle={handleAddQuelle}
              onDeleteQuelle={(id, name) => setDeleteConfirm({ type: 'quelle', id, name })}
              onAssignQuelle={handleAssignQuelle}
              onUnassignQuelle={handleUnassignQuelle}
              onViewQuelle={(quelle) => setTextViewerContent({ title: quelle.name, text: quelle.text })}
            />
          ))}
      </div>

      <TextViewerModal content={textViewerContent} onClose={() => setTextViewerContent(null)} />

      {activeKapitel && (
        <ProcessingDialog
          open={processingDialogOpen}
          onOpenChange={setProcessingDialogOpen}
          kapitelTitle={activeKapitel.title}
          quellenCount={assignedQuellen.length}
          onProcess={handleProcess}
        />
      )}

      <DeleteConfirmDialog
        open={deleteConfirm !== null}
        onOpenChange={(open) => !open && setDeleteConfirm(null)}
        type={deleteConfirm?.type || 'quelle'}
        name={deleteConfirm?.name || ''}
        onConfirm={() => {
          if (deleteConfirm?.type === 'quelle') {
            handleDeleteQuelle(deleteConfirm.id);
          } else if (deleteConfirm?.type === 'kapitel') {
            handleDeleteKapitel(deleteConfirm.id);
          }
        }}
      />
    </div>
  );
}

function buildPrompt(heading: string, topic: string, basicInfo?: string) {
  const prompt = `### Aufgabe:
Schreibe einen Absatz in einer wissenschaftlichen Arbeit. Da es nur ein Absatz ist, schreibe keine Einleitung oder Schlussfolgerung/Zusammenfassung. Der Absatz hat die Überschrift "${heading}" und soll genauer das Thema "${topic}" behandeln. Beziehe dich beim Schreiben des Absatzes nur auf die oben gegebenen Informationen und nutze nichts aus deinem eigenen Wissen. Fokussiere dich außerdem genau auf das Thema, das ich vorgegeben habe, da andere Informationen hierzu bereits behandelt worden sind oder noch behandelt werden; kurzum, schreibe wirklich nur über das vorgegebene Thema. Wichtig ist, dass Informationen, die aus dem obigen Text übernommen werden, so umgeschrieben werden sollen, dass der obige Text nicht mehr zu erkennen ist – das Ergebnis also einzigartig ist. Der Text soll so lang sein, wie er sein muss, um alle relevanten Informationen zu integrieren; ziehe ihn nicht unnötig in die Länge, aber lasse auch nichts Relevantes weg. Sollte der Text keine sinnvollen Informationen zu dem gegebenen Thema enthalten, kannst du mir das sagen und den Text dann nicht schreiben; gib mir dann eine kurze Erklärung, warum der Text nicht zum Thema gepasst hat. Integriere außerdem die Quellen (mit Seitenzahlen, wenn diese gegeben wurden) aus dem oberen Text an den richtigen Stellen. Der gegebene Text hat sicherlich mehr Informationen zu manchen Themen und weniger zu anderen. Fokussiere dich auf die Themen, zu denen du wirklich konkrete und tiefe Einblicke geben kannst. Dieser Text ist nur einer von 10, die ich zu diesem Thema habe. Das bedeutet, wenn du eine Dimension nur wenig oder gar nicht behandelst, habe ich dennoch viele Informationen zu dieser in einem anderen Text. Genauer ausgedrückt, schreibst du gerade einen von 10 Texten, die später das Kapitel ergeben werden. Das bedeutet auch, dass du dich wirklich auf das Wichtigste beschränken kannst und nicht unnötiges schreiben musst. Schreibe keine Zusammenfassung oder Schlussfolgerung am Ende. Nur reine Informationen. Formuliere den Text ohne dass du ; verwendest, außer zwischen zwei Quellen.`;

  const grundInfo = basicInfo?.trim()
    ? `\n\nGrundlegende Informationen, die durchgehend berücksichtigt werden sollen:\n${basicInfo.trim()}`
    : '';

  return `${prompt}${grundInfo}`;
}

function deriveKapitelStatus(
  runs: FirebaseKapitelRun[]
): 'nicht-verarbeitet' | 'in-bearbeitung' | 'fertig' {
  if (!runs || runs.length === 0) return 'nicht-verarbeitet';
  const latestRun = runs[0];
  if (latestRun.combined && latestRun.combined.combinedContent) {
    return 'fertig';
  }
  return 'in-bearbeitung';
}
