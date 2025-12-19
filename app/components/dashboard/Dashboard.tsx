'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { KapitelNavigator } from './KapitelNavigator';
import { KapitelWorkspace } from './KapitelWorkspace';
import { ProjektHeader } from './ProjektHeader';
import { QuellenPanel } from './QuellenPanel';
import { TextViewerModal } from './TextViewerModal';
import { QuelleViewerModal } from './QuelleViewerModal';
import { ProcessingDialog } from './ProcessingDialog';
import { ShortenDialog } from './ShortenDialog';
import { LeseflussDialog } from './LeseflussDialog';
import { CombinedRefinementDialog } from './CombinedRefinementDialog';
import { ShortenedRefinementDialog } from './ShortenedRefinementDialog';
import { LeseflussRefinementDialog } from './LeseflussRefinementDialog';
import { ResultRefinementDialog } from './ResultRefinementDialog';
import { DeleteConfirmDialog } from './DeleteConfirmDialog';
import { DashboardSkeleton } from './DashboardSkeleton';
import { QuellenPanelSkeleton } from './QuellenPanelSkeleton';
import { KapitelWorkspaceSkeleton } from './KapitelWorkspaceSkeleton';
import { ViewportWarning } from '@/app/components/viewport-warning';
import { toast } from 'sonner';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import type { PromptStage, PromptTemplate, ActivePromptSelections } from '@/app/types/prompts';
import { STAGE_CONFIG } from '@/app/lib/prompts/promptConfig';

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
  getQuelleContent,
  getUserQuellen,
  type Quelle as FirebaseQuelle,
  type ImageMetadata,
} from '@/app/actions/quellen';
import {
  createKapitel,
  updateKapitelQuellen,
  deleteKapitel as deleteKapitelAction,
  updateKapitelTitle,
  createKapitelRun,
  createShortenRun,
  createLeseflussRun,
  getKapitelRuns,
  getUserKapitels,
  type KapitelRun as FirebaseKapitelRun,
  type Kapitel as FirebaseKapitel,
} from '@/app/actions/kapitels';
import { createProject, deleteProject, type Project as FirebaseProject } from '@/app/actions/projects';

// Firebase real-time
import { useAuth } from '@/app/components/providers/AuthProvider';
import { firebaseApp } from '@/app/lib/firebase/config';
import {
  getFirestore,
  collection,
  onSnapshot,
  query,
  orderBy,
  limit,
  where,
  doc,
  getDoc,
  getDocs,
  updateDoc,
  serverTimestamp,
  addDoc,
} from 'firebase/firestore';
import Cookies from 'js-cookie';
import { fetchOpenAIKeyStatus, type OpenAIKeyStatus } from '@/app/lib/api/openaiKeyClient';
import { getQuellenPanelState, setQuellenPanelState } from '@/app/lib/storage/preferences';

const API_BASE_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://localhost:8000';
const RUN_HISTORY_LIMIT = 10;
const MAX_RUN_HISTORY_LIMIT = 200;

type PromptChoiceDialogProps = {
  open: boolean;
  stages: PromptStage[];
  templates: PromptTemplate[];
  active: ActivePromptSelections;
  onConfirm: (choices: Record<PromptStage, string | 'default'>) => void;
  onCancel: () => void;
};

function PromptSelectDialog({ open, stages, templates, active, onConfirm, onCancel }: PromptChoiceDialogProps) {
  const [choices, setChoices] = useState<Record<PromptStage, string | 'default'>>(() => {
    const initial = {} as Record<PromptStage, string | 'default'>;
    stages.forEach((s) => {
      initial[s] = (active[s] as string | 'default') || 'default';
    });
    return initial;
  });

  useEffect(() => {
    const init = {} as Record<PromptStage, string | 'default'>;
    stages.forEach((s) => {
      init[s] = (active[s] as string | 'default') || 'default';
    });
    setChoices(init);
  }, [stages, active, open]);

  return (
    <Dialog open={open} onOpenChange={(val) => !val && onCancel()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Prompt auswählen</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          {stages.map((stage) => {
            const stageTemplates = templates.filter((t) => t.stage === stage);
            const config = STAGE_CONFIG[stage];
            return (
              <Card key={stage} className="p-3">
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <p className="text-sm font-medium">{config.label}</p>
                    <p className="text-xs text-muted-foreground">
                      Pflicht: {config.requiredPlaceholders.length ? config.requiredPlaceholders.join(", ") : "Keine"}
                    </p>
                  </div>
                  <Select
                    value={choices[stage] || 'default'}
                    onValueChange={(val) => setChoices((prev) => ({ ...prev, [stage]: val as string | 'default' }))}
                  >
                    <SelectTrigger className="w-64">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="default">System-Standard</SelectItem>
                      {stageTemplates.map((tpl) => (
                        <SelectItem key={tpl.id} value={tpl.id}>
                          {tpl.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <p className="text-xs text-muted-foreground line-clamp-2 font-mono">
                  {stageTemplates.find((t) => t.id === choices[stage])?.instructions?.slice(0, 160) || 'System-Standard'}
                </p>
              </Card>
            );
          })}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            Abbrechen
          </Button>
          <Button onClick={() => onConfirm(choices)}>Weiter</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface DashboardProps {
  initialKapitels: FirebaseKapitel[];
  initialQuellen: FirebaseQuelle[];
  initialProjekt: FirebaseProject;
  initialProjekte: FirebaseProject[];
  initialRuns?: FirebaseKapitelRun[];
}

export function Dashboard({
  initialKapitels,
  initialQuellen,
  initialProjekt,
  initialProjekte,
  initialRuns = [],
}: DashboardProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user } = useAuth();
  // Start with skeleton to avoid empty flash before data appears
  const [isLoading, setIsLoading] = useState(true);
  const [isQuellenLoading, setIsQuellenLoading] = useState(false);

  const initialProjektList = initialProjekte.length ? initialProjekte : [initialProjekt];
  const [projekt, setProjekt] = useState<Projekt>({
    id: initialProjekt.id,
    name: initialProjekt.name,
    createdAt: new Date(initialProjekt.createdAt),
  });
  const [projekte, setProjekte] = useState<Projekt[]>(
    initialProjektList.map((p) => ({
      id: p.id,
      name: p.name,
      createdAt: new Date(p.createdAt),
    }))
  );

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

  const [fbRuns, setFbRuns] = useState<FirebaseKapitelRun[]>(initialRuns);
  const keepInitialRunsRef = useRef(initialRuns.length > 0);
  const [runListLimit, setRunListLimit] = useState<number>(RUN_HISTORY_LIMIT);
  const [allRunsLoaded, setAllRunsLoaded] = useState(false);
  const [isKapitelLoading, setIsKapitelLoading] = useState(initialRuns.length === 0);
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const selectedRun = runs.find((r) => r.id === selectedRunId);
  const hasShownNoticeRef = useRef(false);
  const [keyStatus, setKeyStatus] = useState<OpenAIKeyStatus | null>(null);
  const [keyStatusLoading, setKeyStatusLoading] = useState(false);
  const keyNoticeShownRef = useRef(false);
  const [promptTemplates, setPromptTemplates] = useState<PromptTemplate[]>([]);
  const [promptActive, setPromptActive] = useState<ActivePromptSelections>({});
  const [askOnEachProcess, setAskOnEachProcess] = useState(false);
  const [promptChooser, setPromptChooser] = useState<{
    stages: PromptStage[];
    resolve: (choices: Record<PromptStage, string | 'default'> | null) => void;
  } | null>(null);

  const handleAuthFailure = useCallback(() => {
    toast.error('Sitzung erforderlich', {
      description: 'Bitte melde dich erneut an.',
      id: 'auth-required',
    });
    router.replace('/login?reason=unauthenticated');
  }, [router]);

  const ensureOpenAIAccess = useCallback(async (): Promise<boolean> => {
    if (keyStatusLoading) {
      toast.info('Bitte warten', {
        description: 'Wir prüfen deinen OpenAI-Key...',
        id: 'openai-key-loading',
      });
      return false;
    }

    let status = keyStatus;

    if (!status) {
      const token = Cookies.get('__session');
      if (!token) {
        handleAuthFailure();
        return false;
      }

      try {
        setKeyStatusLoading(true);
        status = await fetchOpenAIKeyStatus(token);
        setKeyStatus(status);
      } catch (err) {
        console.error('OpenAI key status failed', err);
        if (!keyNoticeShownRef.current) {
          keyNoticeShownRef.current = true;
          toast.error('OpenAI Key erforderlich', {
            description: 'Bitte hinterlege deinen OpenAI Key im Profil, sonst können keine Läufe gestartet werden.',
            id: 'openai-key-missing',
          });
        }
        return false;
      } finally {
        setKeyStatusLoading(false);
      }
    }

    if (!status) {
      return false;
    }

    if (!status.hasKey && !status.allowPlatformKey) {
      if (!keyNoticeShownRef.current) {
        keyNoticeShownRef.current = true;
        toast.error('OpenAI Key erforderlich', {
          description: 'Füge deinen OpenAI Key im Profil hinzu, um weiterzumachen.',
          id: 'openai-key-missing',
        });
      }
      router.push('/profil');
      return false;
    }

    return true;
  }, [handleAuthFailure, keyStatus, keyStatusLoading, router]);

  const notifyServerDown = useCallback(
    (toastId: string | number = 'fastapi-down') => {
      toast.error('Server nicht erreichbar', {
        description:
          'Der FastAPI-Server antwortet aktuell nicht. Das ist ein Server-Problem - du kannst nichts tun außer es später erneut zu versuchen.',
        id: toastId,
      });
    },
    []
  );

  useEffect(() => {
    if (hasShownNoticeRef.current) return;
    const notice = searchParams.get('notice');
    if (!notice) return;
    hasShownNoticeRef.current = true;

    if (notice === 'already-authenticated') {
      toast.info('Bereits angemeldet', {
        description: 'Du bist bereits eingeloggt.',
      });
      router.replace('/dashboard');
    }
  }, [router, searchParams]);

  const handleSelectRun = useCallback((id: string) => {
    setIsKapitelLoading(true);
    setSelectedRunId(id);
  }, []);

  const [showQuellenPanel, setShowQuellenPanel] = useState(() => getQuellenPanelState());
  const [textViewerContent, setTextViewerContent] = useState<{
    title: string;
    text: string;
  } | null>(null);
  const [quelleViewer, setQuelleViewer] = useState<Quelle | null>(null);
  const [quelleViewerLoading, setQuelleViewerLoading] = useState(false);
  const [processingDialogOpen, setProcessingDialogOpen] = useState(false);

  // Persist Quellen panel state to localStorage
  useEffect(() => {
    setQuellenPanelState(showQuellenPanel);
  }, [showQuellenPanel]);
  const [shortenDialogOpen, setShortenDialogOpen] = useState(false);
  const [leseflussDialogOpen, setLeseflussDialogOpen] = useState(false);
  const [combinedRefinementDialogOpen, setCombinedRefinementDialogOpen] = useState(false);
  const [shortenedRefinementDialogOpen, setShortenedRefinementDialogOpen] = useState(false);
  const [leseflussRefinementDialogOpen, setLeseflussRefinementDialogOpen] = useState(false);
  const [resultRefinementDialogOpen, setResultRefinementDialogOpen] = useState(false);
  const [resultRefinementTarget, setResultRefinementTarget] = useState<{ quelleId: string; quelleName: string } | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<{
    type: 'quelle' | 'kapitel' | 'projekt';
    id: string;
    name: string;
  } | null>(null);
  const [isAddingQuelle, setIsAddingQuelle] = useState(false);
  const [assigningQuelleIds, setAssigningQuelleIds] = useState<string[]>([]);
  const [unassigningQuelleIds, setUnassigningQuelleIds] = useState<string[]>([]);
  const [deletingQuelleIds, setDeletingQuelleIds] = useState<string[]>([]);
  const [isProcessingRun, setIsProcessingRun] = useState(false);
  const [isCombining, setIsCombining] = useState(false);
  const [isShortening, setIsShortening] = useState(false);
  const [isImprovingLesefluss, setIsImprovingLesefluss] = useState(false);
  const [isCreatingKapitel, setIsCreatingKapitel] = useState(false);
  const [isEditingKapitel, setIsEditingKapitel] = useState(false);
  const [isCreatingProjekt, setIsCreatingProjekt] = useState(false);

  const loadProjektData = useCallback(async (projektId: string) => {
    setIsKapitelLoading(true);
    setRunListLimit(RUN_HISTORY_LIMIT);
    setAllRunsLoaded(false);
    const [fbQuellen, fbKapitels] = await Promise.all([
      getUserQuellen(projektId),
      getUserKapitels(projektId, false, RUN_HISTORY_LIMIT),
    ]);
    setQuellen(fbQuellen.map((q) => transformQuelleToUI(q, projektId)));
    setKapiteln(fbKapitels.map((k) => transformKapitelToUI(k, projektId)));
    const firstKapitelId = fbKapitels[0]?.id || '';
    setActiveKapitelId(firstKapitelId);
    setSelectedRunId(null);
    setFbRuns([]);

    if (firstKapitelId) {
      const runs = await getKapitelRuns(firstKapitelId, RUN_HISTORY_LIMIT);
      setFbRuns(runs);
      keepInitialRunsRef.current = runs.length > 0;
      setIsKapitelLoading(runs.length === 0);
    } else {
      setIsKapitelLoading(false);
    }
  }, []);

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
      projektId: projekt.id,
      nummer,
      quelleIds: [],
      parentId,
      order: Date.now(),
      createdAt: serverTimestamp(),
      updatedAt: serverTimestamp(),
      archived: false,
    });
    return docRef.id;
  }, [user?.uid, projekt.id]);

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

  const deleteKapitelClient = useCallback(
    async (kapitelId: string, deleteStrategy: 'promote' | 'cascade' = 'promote') => {
      if (!user?.uid) throw new Error('Kein Nutzer angemeldet');
      const db = getFirestore(firebaseApp);

      const archiveRec = async (id: string, strategy: 'promote' | 'cascade') => {
        const kapitelRef = doc(db, 'users', user.uid, 'kapitels', id);
        const kapitelSnap = await getDoc(kapitelRef);
        if (!kapitelSnap.exists()) return;
        const parentId = (kapitelSnap.data() as any).parentId ?? null;

        const kapitelsRef = collection(db, 'users', user.uid, 'kapitels');
        const childrenQ = query(kapitelsRef, where('parentId', '==', id), where('archived', '==', false));
        const childrenSnap = await getDocs(childrenQ);

        if (strategy === 'cascade') {
          for (const child of childrenSnap.docs) {
            await archiveRec(child.id, 'cascade');
          }
        } else {
          for (const child of childrenSnap.docs) {
            await updateDoc(doc(db, 'users', user.uid, 'kapitels', child.id), {
              parentId,
              updatedAt: serverTimestamp(),
            });
          }
        }

        await updateDoc(kapitelRef, {
          archived: true,
          archivedAt: serverTimestamp(),
          updatedAt: serverTimestamp(),
        });
      };

      await archiveRec(kapitelId, deleteStrategy);
    },
    [user?.uid]
  );

  // When the active Kapitel changes, seed runs from initial data while real-time listeners attach
  useEffect(() => {
    if (!activeKapitelId) {
      setFbRuns([]);
      setRuns([]);
      setSelectedRunId(null);
      setIsKapitelLoading(false);
      return;
    }

    setIsKapitelLoading(true);
    setSelectedRunId(null);
    setRunListLimit(RUN_HISTORY_LIMIT);
    setAllRunsLoaded(false);

    if (keepInitialRunsRef.current) {
      // Preserve the initially provided runs once; subsequent Kapitel switches clear state
      setIsKapitelLoading(false);
      keepInitialRunsRef.current = false;
      return;
    }

    setFbRuns([]);
    setRuns([]);
  }, [activeKapitelId]);

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
    const q = query(runsRef, where('archived', '==', false), orderBy('index', 'desc'), limit(runListLimit));

    const unsubscribeRuns = onSnapshot(
      q,
      (snapshot) => {
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
              createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
              updatedAt: data.updatedAt?.toDate?.()?.toISOString(),
              promptTemplateId: data.promptTemplateId,
              promptPayload: data.promptPayload,
              autoCombine: data.autoCombine ?? false,
              results: existing?.results || [],
              artifacts: existing?.artifacts,
              artifactsStatus: data.artifactsStatus,
              resultsExpectedCount: data.resultsExpectedCount,
              resultsCompletedCount: data.resultsCompletedCount,
              resultsWithContentCount: data.resultsWithContentCount,
              lastResultAt: data.lastResultAt?.toDate?.()?.toISOString() ?? null,
              lastActivityAt: data.lastActivityAt?.toDate?.()?.toISOString() ?? null,
              ueberschrift: data.ueberschrift || existing?.ueberschrift || '',
              thema: data.thema || existing?.thema || '',
              grundlegendeInformationen: data.grundlegendeInformationen ?? existing?.grundlegendeInformationen ?? null,
            } as FirebaseKapitelRun;
          });
          return baseRuns;
        });

        if (!snapshot.empty && !selectedRunId) {
          handleSelectRun(snapshot.docs[0].id);
        }

        if (snapshot.empty) {
          setIsKapitelLoading(false);
        }
      },
      (error) => {
        console.error('Error listening to runs:', error);
        setIsKapitelLoading(false);
      }
    );

    return () => {
      unsubscribeRuns();
    };
  }, [user?.uid, activeKapitelId, runListLimit, selectedRunId, handleSelectRun]);

  // Load data (artifacts/results) only for the selected run
  useEffect(() => {
    if (!user?.uid || !activeKapitelId || !selectedRunId) {
      return;
    }

    const db = getFirestore(firebaseApp);

    const artifactsRef = collection(
      db,
      'users',
      user.uid,
      'kapitels',
      activeKapitelId,
      'runs',
      selectedRunId,
      'artifacts'
    );

    const resultsRef = collection(
      db,
      'users',
      user.uid,
      'kapitels',
      activeKapitelId,
      'runs',
      selectedRunId,
      'results'
    );

    setIsKapitelLoading(true);
    let hasData = false;
    let settledOnce = false;

    // Batch multiple listener updates to reduce re-renders
    let pendingUpdate: Partial<FirebaseKapitelRun> = {};
    let updateTimeout: NodeJS.Timeout | null = null;

    // Track when both listeners have fired at least once
    let listenersSettled = 0;
    const totalListeners = 2;

    const flushBatchedUpdate = () => {
      if (Object.keys(pendingUpdate).length > 0) {
        setFbRuns((prev) => prev.map((run) => (run.id === selectedRunId ? { ...run, ...pendingUpdate } : run)));
        pendingUpdate = {};
      }
    };

    const updateRunBatched = (partial: Partial<FirebaseKapitelRun>) => {
      pendingUpdate = { ...pendingUpdate, ...partial };

      if (updateTimeout) {
        clearTimeout(updateTimeout);
      }

      updateTimeout = setTimeout(flushBatchedUpdate, 50);
    };

    const finishIfNeeded = () => {
      if (!settledOnce) {
        settledOnce = true;
        setIsKapitelLoading(false);
      }
    };

    const checkListenerSettled = () => {
      listenersSettled++;
      if (listenersSettled >= totalListeners) {
        finishIfNeeded();
      }
    };

    const normalizeRefinement = (refinement: any) =>
      refinement
        ? {
            rootVersionId: 'root' as const,
            activeVersionId: refinement.activeVersionId ?? 'root',
            maxDepth: refinement.maxDepth ?? 4,
            costTotalUsd: refinement.costTotalUsd ?? 0,
            initializedAt: refinement.initializedAt?.toDate?.()?.toISOString() || new Date().toISOString(),
            selectedAt: refinement.selectedAt?.toDate?.()?.toISOString() ?? null,
          }
        : {
            rootVersionId: 'root' as const,
            activeVersionId: 'root',
            maxDepth: 4,
            costTotalUsd: 0,
            initializedAt: new Date().toISOString(),
            selectedAt: null,
          };

    const normalizeUsage = (usage: any) =>
      usage
        ? {
            inputTokens: usage.inputTokens ?? 0,
            cachedInputTokens: usage.cachedInputTokens ?? 0,
            outputTokens: usage.outputTokens ?? 0,
            reasoningTokens: usage.reasoningTokens ?? 0,
            totalTokens: usage.totalTokens ?? 0,
          }
        : { inputTokens: 0, cachedInputTokens: 0, outputTokens: 0, reasoningTokens: 0, totalTokens: 0 };

    const artifactsUnsub = onSnapshot(
      artifactsRef,
      (artifactSnap) => {
        const artifacts: any = { combined: null, shortened: null, lesefluss: null };

        artifactSnap.docs.forEach((d) => {
          const data: any = d.data();
          const artifactId = d.id;
          const refinement = normalizeRefinement(data.refinement);
          const usage = normalizeUsage(data.usage);

          if (artifactId === 'combined') {
            artifacts.combined = {
              id: 'combined',
              content: data.content ?? '',
              sourceQuelleIds: data.sourceQuelleIds ?? [],
              heading: data.heading ?? '',
              topic: data.topic ?? '',
              model: data.model ?? '',
              usage,
              costUsd: data.costUsd ?? 0,
              refinement,
              createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
              updatedAt: data.updatedAt?.toDate?.()?.toISOString(),
            };
          } else if (artifactId === 'shortened') {
            artifacts.shortened = {
              id: 'shortened',
              content: data.content ?? '',
              explanation: data.explanation,
              originalLength: data.originalLength ?? 0,
              shortenedLength: data.shortenedLength ?? 0,
              usedKapitelIds: data.usedKapitelIds ?? [],
              model: data.model ?? '',
              usage,
              costUsd: data.costUsd ?? 0,
              refinement,
              createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
              updatedAt: data.updatedAt?.toDate?.()?.toISOString(),
            };
          } else if (artifactId === 'lesefluss') {
            artifacts.lesefluss = {
              id: 'lesefluss',
              content: data.content ?? '',
              aufgabenstellung: data.aufgabenstellung ?? '',
              explanation: data.explanation,
              originalLength: data.originalLength,
              leseflussLength: data.leseflussLength ?? 0,
              usedKapitelIds: data.usedKapitelIds ?? [],
              model: data.model ?? '',
              usage,
              costUsd: data.costUsd ?? 0,
              refinement,
              createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
              updatedAt: data.updatedAt?.toDate?.()?.toISOString(),
            };
          }
        });

        updateRunBatched({ artifacts });
        hasData = hasData || Boolean(artifacts.combined || artifacts.shortened || artifacts.lesefluss);
        if (hasData) finishIfNeeded();
        checkListenerSettled();
      },
      (err) => {
        console.error('Artifacts listen failed:', err);
        checkListenerSettled();
      }
    );

    const resultsUnsub = onSnapshot(
      resultsRef,
      (resSnapshot) => {
        const results = resSnapshot.docs.map((resDoc) => {
          const resData: any = resDoc.data();
          return {
            quelleId: resDoc.id,
            userInput: resData.userInput ?? '',
            content: resData.content ?? '',
            hasContent: typeof resData.hasContent === 'boolean' ? resData.hasContent : true,
            model: resData.model ?? '',
            usage: normalizeUsage(resData.usage),
            costUsd: resData.costUsd ?? 0,
            refinement: normalizeRefinement(resData.refinement),
            createdAt: resData.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
            updatedAt: resData.updatedAt?.toDate?.()?.toISOString(),
          };
        });

        updateRunBatched({ results });
        hasData = hasData || results.length > 0;
        if (hasData) finishIfNeeded();
        if (!hasData && resSnapshot.empty) {
          finishIfNeeded();
        }
        checkListenerSettled();
      },
      (err) => {
        console.error('Results listen failed:', err);
        checkListenerSettled();
      }
    );

    return () => {
      if (updateTimeout) {
        clearTimeout(updateTimeout);
        flushBatchedUpdate();
      }
      artifactsUnsub();
      resultsUnsub();
    };
  }, [user?.uid, activeKapitelId, selectedRunId]);

  // Realtime Kapitels list for the active project (status comes from denormalized `latestRun`)
  useEffect(() => {
    if (!user?.uid || !projekt?.id) return;

    const db = getFirestore(firebaseApp);
    const kapitelsRef = collection(db, 'users', user.uid, 'kapitels');
    const q = query(
      kapitelsRef,
      where('projektId', '==', projekt.id),
      where('archived', '==', false),
      orderBy('order', 'asc')
    );

    const unsub = onSnapshot(
      q,
      (snap) => {
        const fb = snap.docs.map((d) => {
          const data: any = d.data();
          return {
            id: d.id,
            title: data.title || '',
            projektId: data.projektId || projekt.id,
            nummer: data.nummer || '1',
            createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
            updatedAt: data.updatedAt?.toDate?.()?.toISOString(),
            archived: Boolean(data.archived),
            archivedAt: data.archivedAt?.toDate?.()?.toISOString(),
            quelleIds: data.quelleIds || [],
            parentId: data.parentId ?? null,
            order: data.order ?? 0,
            latestRun: data.latestRun
              ? {
                  runId: data.latestRun.runId,
                  index: data.latestRun.index,
                  status: data.latestRun.status,
                  updatedAt: data.latestRun.updatedAt?.toDate?.()?.toISOString() || new Date().toISOString(),
                }
              : undefined,
          };
        });

        const ui = fb.map((k) => transformKapitelToUI(k as any, projekt.id));
        setKapiteln(ui);

        setActiveKapitelId((prev) => {
          if (!ui.length) return '';
          if (prev && ui.some((k) => k.id === prev)) return prev;
          return ui[0].id;
        });
      },
      (err) => {
        console.error('Error listening to kapitels:', err);
      }
    );

    return () => unsub();
  }, [user?.uid, projekt.id]);

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
      handleSelectRun(uiRuns[0].id);
    }

  }, [fbRuns, quellen, activeKapitelId, activeKapitel?.assignedQuellenIds, selectedRunId, handleSelectRun]);

  // Handlers
  const handleSwitchProjekt = useCallback(
    async (projektId: string, fallbackProjekt?: Projekt) => {
      if (projektId === projekt.id) return;
      try {
        setIsLoading(true);
        await loadProjektData(projektId);
        const next = projekte.find((p) => p.id === projektId) || fallbackProjekt;
        if (next) {
          setProjekt(next);
        } else {
          // minimal fallback if not found
          setProjekt({ id: projektId, name: 'Projekt', createdAt: new Date() });
        }
      } catch (error: any) {
        console.error('Projekt wechseln fehlgeschlagen:', error);
        toast.error('Projekt konnte nicht geladen werden', { description: error.message });
      } finally {
        setIsLoading(false);
      }
    },
    [loadProjektData, projekt.id, projekte]
  );

  const handleCreateProjekt = useCallback(
    async (name: string) => {
      if (isCreatingProjekt) return;
      setIsCreatingProjekt(true);
      const toastId = toast.loading('Projekt wird erstellt...');

      try {
        const result = await createProject(name);
        if (!result.success || !result.id) {
          throw new Error(result.error || 'Projekt konnte nicht erstellt werden.');
        }
        const newProjekt: Projekt = {
          id: result.id,
          name,
          createdAt: new Date(),
        };
        setProjekte((prev) => [newProjekt, ...prev]);
        // Switch immediately using the newly created project
        setProjekt(newProjekt);
        await loadProjektData(result.id);
        toast.success('Projekt erstellt', { description: `"${name}" wurde erstellt.`, id: toastId });
      } catch (error: any) {
        console.error('Projekt erstellen fehlgeschlagen:', error);
        toast.error('Projekt konnte nicht erstellt werden', { description: error.message, id: toastId });
      } finally {
        setIsCreatingProjekt(false);
      }
    },
    [loadProjektData, isCreatingProjekt]
  );

  const handleDeleteProjekt = useCallback(
    async (projektId: string) => {
      if (projekte.length <= 1) {
        toast.error('Projekt löschen nicht möglich', { description: 'Mindestens ein Projekt muss bestehen.' });
        return;
      }
      try {
        await deleteProject(projektId);
        const remaining = projekte.filter((p) => p.id !== projektId);
        setProjekte(remaining);
        if (projekt.id === projektId && remaining.length > 0) {
          setProjekt(remaining[0]);
          await loadProjektData(remaining[0].id);
        }
        toast.success('Projekt gelöscht');
      } catch (error: any) {
        console.error('Projekt löschen fehlgeschlagen:', error);
        toast.error('Projekt konnte nicht gelöscht werden', { description: error.message });
      }
    },
    [loadProjektData, projekt.id, projekte]
  );

  const handleAddQuelle = useCallback(
    async (name: string, text: string, imageFiles: File[] = [], advancedFields?: Record<string, any>): Promise<boolean> => {
      if (isAddingQuelle) return false;
      setIsAddingQuelle(true);

      const loadingToast = toast.loading('Quelle wird hinzugefügt...');
      const uploadingToast =
        imageFiles.length > 0
          ? toast.loading(`<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`)
          : undefined;

      let imageMetadata: ImageMetadata[] = [];
      let success = false;

      try {
        // Upload images to Storage first (client-side)
        if (imageFiles.length > 0) {
          const { uploadImagesToStorage } = await import('@/app/lib/firebase/storage');
          imageMetadata = await uploadImagesToStorage(user!.uid, imageFiles);
        }

        // Create Quelle with image metadata (not files) and advanced fields
        const result = await createQuelle(name, text, projekt.id, imageMetadata, advancedFields);

        if (uploadingToast) toast.dismiss(uploadingToast);

        if (result.success) {
          success = true;
          toast.success('Quelle hinzugefügt', {
            description: `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>` mit ${imageFiles.length} Bild(ern)` : ''}.`,
            id: loadingToast,
          });
          // Optimistically update UI
          const newQuelle: Quelle = {
            id: result.id!,
            name,
            text,
            projektId: projekt.id,
            createdAt: new Date(),
            images: result.imageUrls || [],
            // Include advanced fields in optimistic update
            ...advancedFields,
          };
          setQuellen((prev) => [...prev, newQuelle]);
        } else {
          toast.error('Fehler', { description: result.error, id: loadingToast });

          // Cleanup uploaded images if Firestore creation failed
          if (imageMetadata.length > 0) {
            const { deleteImagesFromStorage } = await import('@/app/lib/firebase/storage');
            await deleteImagesFromStorage(imageMetadata.map((img) => img.path));
          }
        }
      } catch (error) {
        if (uploadingToast) toast.dismiss(uploadingToast);
        toast.error('Upload fehlgeschlagen', {
          description: error instanceof Error ? error.message : 'Unbekannter Fehler',
          id: loadingToast,
        });

        // Cleanup uploaded images on error
        if (imageMetadata.length > 0) {
          const { deleteImagesFromStorage } = await import('@/app/lib/firebase/storage');
          await deleteImagesFromStorage(imageMetadata.map((img) => img.path));
        }
      } finally {
        setIsAddingQuelle(false);
      }

      return success;
    },
    [isAddingQuelle, projekt.id, user]
  );

  const handleDeleteQuelle = useCallback(async (id: string) => {
    if (deletingQuelleIds.includes(id)) return;
    setDeletingQuelleIds((prev) => [...prev, id]);
    const toastId = toast.loading('Quelle wird gelöscht...');

    try {
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
        toast.success('Quelle gelöscht', { id: toastId });
      } else {
        toast.error('Fehler', { description: result.error, id: toastId });
      }
    } catch (error: any) {
      toast.error('Fehler', { description: error?.message || 'Quelle konnte nicht gelöscht werden.', id: toastId });
    } finally {
      setDeletingQuelleIds((prev) => prev.filter((qid) => qid !== id));
    }
  }, [deletingQuelleIds]);

  const handleViewQuelle = useCallback(async (quelle: Quelle) => {
    setQuelleViewerLoading(true);
    setQuelleViewer({ ...quelle, text: '' });
    try {
      const content = await getQuelleContent(quelle.id);
      if (content?.text != null) {
        setQuelleViewer((prev) => (prev?.id === quelle.id ? { ...prev, text: content.text } : prev));
      }
    } finally {
      setQuelleViewerLoading(false);
    }
  }, []);

  const handleAssignQuelle = useCallback(
    async (quelleId: string) => {
      if (!activeKapitelId) return;
      if (assigningQuelleIds.includes(quelleId) || unassigningQuelleIds.includes(quelleId)) return;
      const kapitel = kapiteln.find((k) => k.id === activeKapitelId);
      if (!kapitel) return;

      setAssigningQuelleIds((prev) => [...prev, quelleId]);

      const prevQuelleIds = kapitel.assignedQuellenIds;
      const newQuelleIds = [...prevQuelleIds, quelleId];

      // Optimistic update for snappier UI
      setKapiteln((prev) =>
        prev.map((k) => (k.id === activeKapitelId ? { ...k, assignedQuellenIds: newQuelleIds } : k))
      );

      const quelle = quellen.find((q) => q.id === quelleId);

      const toastId = toast.loading('Quelle wird zugewiesen...');

      try {
        await persistKapitelQuellenClient(activeKapitelId, newQuelleIds);
        toast.success('Quelle zugewiesen', {
          id: toastId,
          description: quelle ? `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>` : undefined,
        });
      } catch (clientErr) {
        // Fallback to server action
        const result = await updateKapitelQuellen(activeKapitelId, newQuelleIds);
        if (!result.success) {
          setKapiteln((prev) =>
            prev.map((k) => (k.id === activeKapitelId ? { ...k, assignedQuellenIds: prevQuelleIds } : k))
          );
          toast.error('Fehler', { description: result.error, id: toastId });
        } else {
          toast.success('Quelle zugewiesen', {
            id: toastId,
            description: quelle ? `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>` : undefined,
          });
        }
      } finally {
        setAssigningQuelleIds((prev) => prev.filter((id) => id !== quelleId));
      }
    },
    [activeKapitelId, kapiteln, persistKapitelQuellenClient, quellen, assigningQuelleIds, unassigningQuelleIds]
  );

  const handleUnassignQuelle = useCallback(
    async (quelleId: string) => {
      if (!activeKapitelId) return;
      if (unassigningQuelleIds.includes(quelleId) || assigningQuelleIds.includes(quelleId)) return;
      const kapitel = kapiteln.find((k) => k.id === activeKapitelId);
      if (!kapitel) return;

      setUnassigningQuelleIds((prev) => [...prev, quelleId]);

      const prevQuelleIds = kapitel.assignedQuellenIds;
      const newQuelleIds = prevQuelleIds.filter((id) => id !== quelleId);

      // Optimistic update for snappier UI
      setKapiteln((prev) =>
        prev.map((k) => (k.id === activeKapitelId ? { ...k, assignedQuellenIds: newQuelleIds } : k))
      );

      const quelle = quellen.find((q) => q.id === quelleId);

      const toastId = toast.loading('Quelle wird entfernt...');

      try {
        await persistKapitelQuellenClient(activeKapitelId, newQuelleIds);
        toast.success('Quelle entfernt', {
          id: toastId,
          description: quelle ? `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>` : undefined,
        });
      } catch (clientErr) {
        const result = await updateKapitelQuellen(activeKapitelId, newQuelleIds);
        if (!result.success) {
          setKapiteln((prev) =>
            prev.map((k) => (k.id === activeKapitelId ? { ...k, assignedQuellenIds: prevQuelleIds } : k))
          );
          toast.error('Fehler', { description: result.error, id: toastId });
        } else {
          toast.success('Quelle entfernt', {
            id: toastId,
            description: quelle ? `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>` : undefined,
          });
        }
      } finally {
        setUnassigningQuelleIds((prev) => prev.filter((id) => id !== quelleId));
      }
    },
    [activeKapitelId, kapiteln, persistKapitelQuellenClient, quellen, unassigningQuelleIds, assigningQuelleIds]
  );

  const handleAddKapitel = useCallback(async (title: string, nummer: string) => {
    if (isCreatingKapitel) return;
    setIsCreatingKapitel(true);
    const toastId = toast.loading('Kapitel wird erstellt...');

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
        id: toastId,
      });
    } catch (clientErr) {
      // Fallback to server action
      const result = await createKapitel(title, [], null, nummer, projekt.id);
      if (result.success && result.id) {
        setKapiteln((prev) =>
          prev.map((k) => (k.id === tempId ? { ...k, id: result.id! } : k))
        );
        setActiveKapitelId(result.id);
        toast.success('Kapitel erstellt', {
          description: `"${nummer} ${title}" wurde hinzugefügt.`,
          id: toastId,
        });
      } else {
        // Revert on failure
        setKapiteln((prev) => prev.filter((k) => k.id !== tempId));
        setActiveKapitelId((prev) => (prev === tempId ? kapiteln[0]?.id || '' : prev));
        toast.error('Fehler', { description: result.error || (clientErr as Error).message, id: toastId });
      }
    } finally {
      setIsCreatingKapitel(false);
    }
  }, [createKapitelClient, kapiteln, projekt.id, isCreatingKapitel]);

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
    if (isEditingKapitel) return;
    setIsEditingKapitel(true);
    const toastId = toast.loading('Kapitel wird aktualisiert...');

    const prevKapiteln = kapiteln;
    setKapiteln((prev) => prev.map((k) => (k.id === id ? { ...k, title, nummer } : k)));

    try {
      await updateKapitelTitleClient(id, title, nummer);
      toast.success('Kapitel aktualisiert', {
        description: `"${nummer} ${title}" wurde gespeichert.`,
        id: toastId,
      });
    } catch (clientErr) {
      const result = await updateKapitelTitle(id, title, nummer);
      if (!result.success) {
        setKapiteln(prevKapiteln);
        toast.error('Fehler', { description: result.error || (clientErr as Error).message, id: toastId });
      } else {
        toast.success('Kapitel aktualisiert', {
          description: `"${nummer} ${title}" wurde gespeichert.`,
          id: toastId,
        });
      }
    } finally {
      setIsEditingKapitel(false);
    }
  }, [kapiteln, updateKapitelTitleClient, isEditingKapitel]);

  const renderPromptTemplate = useCallback((template: string, payload: Record<string, string>) => {
    let result = template;
    Object.entries(payload).forEach(([key, value]) => {
      result = result.replaceAll(`{${key}}`, value ?? '');
    });
    return result;
  }, []);

  useEffect(() => {
    const loadPrompts = async () => {
      try {
        const res = await fetch('/api/prompt-templates');
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Prompts konnten nicht geladen werden.');
        setPromptTemplates(data.templates || []);
        setPromptActive(data.active || {});
        setAskOnEachProcess(Boolean(data.askOnEachProcess));
      } catch (err: any) {
        console.error('Prompt templates load failed', err);
        toast.error('Prompts', { description: err?.message || 'Prompts konnten nicht geladen werden.' });
      }
    };
    loadPrompts();
  }, []);

  const applyActivePrompt = useCallback(async (stage: PromptStage, templateId: string | 'default') => {
    setPromptActive((prev) => ({ ...prev, [stage]: templateId }));
    try {
      await fetch('/api/prompt-templates/active', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stage, templateId }),
      });
    } catch (err) {
      console.error('Aktives Prompt setzen fehlgeschlagen', err);
    }
  }, []);

  const getInstructionsFor = useCallback(
    (stage: PromptStage, templateId?: string | 'default') => {
      const targetId = templateId ?? (promptActive[stage] as string | 'default') ?? 'default';
      if (targetId && targetId !== 'default') {
        const tpl = promptTemplates.find((t) => t.id === targetId && t.stage === stage);
        if (tpl?.instructions) return tpl.instructions;
      }
      return STAGE_CONFIG[stage].defaultInstructions;
    },
    [promptActive, promptTemplates]
  );

  const requestPromptChoice = useCallback(
    async (stages: PromptStage[]): Promise<Record<PromptStage, string | 'default'> | null> => {
      // Ensure we have the freshest askOnEachProcess flag in case the user just toggled it elsewhere.
      let shouldAsk = askOnEachProcess;
      if (!askOnEachProcess) {
        try {
          const res = await fetch('/api/prompt-templates/settings');
          if (res.ok) {
            const data = await res.json();
            if (typeof data.askOnEachProcess === 'boolean') {
              shouldAsk = data.askOnEachProcess;
              setAskOnEachProcess(data.askOnEachProcess);
            }
          }
        } catch (err) {
          console.error('askOnEachProcess fetch failed', err);
        }
      }

      if (!shouldAsk) {
        return null;
      }

      return new Promise((resolve) => {
        setPromptChooser({ stages, resolve });
      });
    },
    [askOnEachProcess]
  );

  const handleProcess = useCallback(
    async (settings: ProcessingSettings) => {
      if (!activeKapitel) return;

      if (!(await ensureOpenAIAccess())) return;

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
        handleAuthFailure();
        return;
      }

      const requestedStages: PromptStage[] = settings.directCombine
        ? ['process_quelle', 'combine']
        : ['process_quelle'];
      const providedChoices = settings.promptChoice;
      const choices = providedChoices ?? (await requestPromptChoice(requestedStages));
      if (askOnEachProcess && !providedChoices && choices === null) {
        toast.info('Aktion abgebrochen');
        return;
      }

      const processChoice =
        providedChoices?.process_quelle ??
        choices?.process_quelle ??
        (promptActive.process_quelle as string | 'default') ??
        'default';
      const combineChoice = settings.directCombine
        ? providedChoices?.combine ??
          choices?.combine ??
          (promptActive.combine as string | 'default') ??
          'default'
        : undefined;

      const shouldApplyChoice = Boolean(providedChoices || choices);
      if (shouldApplyChoice) {
        await applyActivePrompt('process_quelle', processChoice);
        if (settings.directCombine && combineChoice) {
          await applyActivePrompt('combine', combineChoice);
        }
      }

      const promptTemplate = getInstructionsFor('process_quelle', processChoice);

      const prompt = renderPromptTemplate(promptTemplate, {
        heading: settings.ueberschrift.trim(),
        topic: settings.thema.trim(),
        grundlegende_infos: settings.grundlegendeInfos?.trim() || '',
      });

      setIsProcessingRun(true);
      setProcessingDialogOpen(false);
      const processingToastId = toast.loading('Verarbeitung gestartet', {
        description: `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`,
      });

      try {
        const result = await createKapitelRun(activeKapitelId, prompt, settings.model, {
          autoCombine: settings.directCombine,
          promptTemplateId: processChoice,
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
              promptTemplateId: processChoice,
              promptPayload: {
                heading: settings.ueberschrift.trim(),
                topic: settings.thema.trim(),
              },
              autoCombine: settings.directCombine,
              results: [],
              artifacts: { combined: null, shortened: null, lesefluss: null },
              ueberschrift: settings.ueberschrift.trim(),
              thema: settings.thema.trim(),
            },
            ...prev,
          ];
        });
        handleSelectRun(result.runId);
        toast.success('Run erstellt', {
          description: 'Die Verarbeitung wurde gestartet...',
          id: processingToastId,
        });

        // Queue processing for all assigned Quellen (mirrors previous implementation)
        const queue = [...assignedQuellen];
        const concurrency = Math.min(3, queue.length || 1);

        let authFailed = false;
        let serverUnavailable = false;

        const worker = async () => {
          while (queue.length > 0 && !authFailed && !serverUnavailable) {
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
                if (response.status === 401) {
                  authFailed = true;
                  queue.length = 0;
                  toast.error('Verarbeitung abgebrochen', {
                    description: 'Bitte melde dich erneut an.',
                    id: processingToastId,
                  });
                  handleAuthFailure();
                  return;
                }

                const errorBody = await response.json().catch(() => ({}));
                const error: any = new Error(errorBody.detail || 'Fehler beim Verarbeiten');
                error.status = response.status;
                throw error;
              }
            } catch (err: any) {
              if (authFailed || serverUnavailable) return;

              const status = err?.status;
              if (status === 401) {
                authFailed = true;
                queue.length = 0;
                toast.error('Verarbeitung abgebrochen', {
                  description: 'Bitte melde dich erneut an.',
                  id: processingToastId,
                });
                handleAuthFailure();
                return;
              }

              if (err instanceof TypeError || (typeof status === 'number' && status >= 500)) {
                serverUnavailable = true;
                queue.length = 0;
                notifyServerDown(processingToastId);
                return;
              }

              console.error(`<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`, err);
              toast.error('Fehler bei einer Quelle', {
                description: err.message || 'Unbekannter Fehler beim Verarbeiten der Quelle',
                id: processingToastId,
              });
            }
          }
        };

        await Promise.all(Array.from({ length: concurrency }, () => worker()));

        if (authFailed || serverUnavailable) {
          return;
        }

        toast.success('Verarbeitung läuft', {
          description: 'Die Quellen werden nacheinander verarbeitet.',
          id: processingToastId,
        });
      } catch (error: any) {
        console.error('Fehler beim Starten der Verarbeitung:', error);
        toast.error('Fehler beim Erstellen des Runs', {
          description: error.message || 'Ein Fehler ist aufgetreten.',
          id: processingToastId,
        });
      } finally {
        setIsProcessingRun(false);
      }
    },
    [
      activeKapitelId,
      activeKapitel,
      ensureOpenAIAccess,
      handleAuthFailure,
      handleSelectRun,
      notifyServerDown,
      quellen,
      renderPromptTemplate,
      requestPromptChoice,
      askOnEachProcess,
      promptActive,
      applyActivePrompt,
      getInstructionsFor,
      isProcessingRun,
    ]
  );

  const handleCombineTexts = useCallback(async () => {
    if (!activeKapitelId || !selectedRun) {
      toast.error('Kein Run ausgewählt');
      return;
    }

    if (!(await ensureOpenAIAccess())) return;

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
      handleAuthFailure();
      return;
    }

    if (isCombining) return;
    setIsCombining(true);

    if (askOnEachProcess) {
      const choice = await requestPromptChoice(['combine']);
      if (!choice) {
        toast.info('Aktion abgebrochen');
        setIsCombining(false);
        return;
      }
      await applyActivePrompt('combine', choice.combine ?? 'default');
    }

    const combineToastId = toast.loading('Texte kombinieren', {
      description: 'Die Texte werden kombiniert...',
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
        if (response.status === 401) {
          toast.error('Kombination abgebrochen', {
            description: 'Bitte melde dich erneut an.',
            id: 'combine',
          });
          handleAuthFailure();
          return;
        }

        if (response.status >= 500) {
          notifyServerDown(combineToastId);
          return;
        }

        const error = await response.json().catch(() => ({}));
        const err: any = new Error(error.detail || 'Fehler beim Kombinieren');
        err.status = response.status;
        throw err;
      }

      toast.success('Kombination gestartet', {
        description: 'Die Texte werden nun zusammengeführt.',
        id: combineToastId,
      });
      } catch (err: any) {
        if (err instanceof TypeError) {
          notifyServerDown(combineToastId);
          setIsCombining(false);
          return;
        }

        if (err?.status === 401) {
          handleAuthFailure();
          setIsCombining(false);
        return;
      }

      console.error('Fehler beim Kombinieren:', err);
        toast.error('Combine fehlgeschlagen', {
          description: err.message || 'Unbekannter Fehler beim Kombinieren',
          id: combineToastId,
        });
      } finally {
      setIsCombining(false);
    }
  }, [
    activeKapitelId,
    ensureOpenAIAccess,
    handleAuthFailure,
    notifyServerDown,
    selectedRun,
    askOnEachProcess,
    requestPromptChoice,
    applyActivePrompt,
    isCombining,
  ]);

  const handleShorten = useCallback(
    async (contextKapitelIds: string[], model: string, promptChoice?: Partial<Record<PromptStage, string | 'default'>>) => {
      if (!activeKapitel || !selectedRun) return;

      if (!(await ensureOpenAIAccess())) return;

      if (contextKapitelIds.length === 0) {
        toast.error('Keine Kontextkapitel ausgewählt', {
          description: 'Wähle mindestens ein Kapitel als Kontext aus.',
        });
        return;
      }

      if (isShortening) return;
      setIsShortening(true);

      const providedChoices = promptChoice;
      if (askOnEachProcess && !providedChoices) {
        const choice = await requestPromptChoice(['shorten', 'summary']);
        if (!choice) {
          toast.info('Aktion abgebrochen');
          setIsShortening(false);
          return;
        }
        await applyActivePrompt('shorten', choice.shorten ?? 'default');
        await applyActivePrompt('summary', choice.summary ?? 'default');
      }
      if (providedChoices) {
        await applyActivePrompt('shorten', providedChoices.shorten ?? 'default');
        await applyActivePrompt('summary', providedChoices.summary ?? 'default');
      }

      const shortenToastId = toast.loading('Text wird gekürzt', {
        description: 'Der Text wird mit Hilfe der ausgewählten Kapitel gekürzt...',
      });

      try {
        const result = await createShortenRun(
          activeKapitelId,
          selectedRun.id,
          contextKapitelIds,
          model as 'gpt-5-nano' | 'gpt-5-mini' | 'gpt-5.2'
        );

        if (!result?.success) {
          const message = result?.error || 'Kürzung konnte nicht gestartet werden.';
          const lower = message.toLowerCase();

          if (lower.includes('sitzung')) {
            toast.error('Kürzung abgebrochen', {
              description: message,
              id: shortenToastId,
            });
            handleAuthFailure();
            return;
          }

          if (lower.includes('fastapi-server')) {
            notifyServerDown(shortenToastId);
            return;
          }

          toast.error('Kürzung fehlgeschlagen', {
            description: message,
            id: shortenToastId,
          });
          return;
        }

        toast.success('Kürzung gestartet', {
          description: 'Der Text wird nun gekürzt und entdupliziert.',
          id: shortenToastId,
        });
      } catch (err: any) {
        console.error('Fehler beim Kürzen:', err);
        const message = err?.message || 'Unbekannter Fehler beim Kürzen';

        if (message.toLowerCase().includes('sitzung')) {
          toast.error('Kürzung abgebrochen', {
            description: message,
            id: shortenToastId,
          });
          handleAuthFailure();
          return;
        }

        if (message.toLowerCase().includes('fastapi-server')) {
          notifyServerDown(shortenToastId);
          return;
        }

        toast.error('Kürzung fehlgeschlagen', {
          description: message,
          id: shortenToastId,
        });
      } finally {
        setIsShortening(false);
      }
    },
    [
      activeKapitelId,
      activeKapitel,
      ensureOpenAIAccess,
      handleAuthFailure,
      notifyServerDown,
      selectedRun,
      askOnEachProcess,
      requestPromptChoice,
      applyActivePrompt,
      isShortening,
    ]
  );

  const handleLesefluss = useCallback(
    async (
      contextKapitelIds: string[],
      aufgabenstellung: string,
      model: string,
      promptChoice?: Partial<Record<PromptStage, string | 'default'>>
    ) => {
      if (!activeKapitel || !selectedRun) return;

      if (!(await ensureOpenAIAccess())) return;

      if (contextKapitelIds.length === 0) {
        toast.error('Keine Kontextkapitel ausgewählt', {
          description: 'Wähle mindestens ein Kapitel als Kontext aus.',
        });
        return;
      }

      if (isImprovingLesefluss) return;
      setIsImprovingLesefluss(true);

      const providedChoices = promptChoice;
      if (askOnEachProcess && !providedChoices) {
        const choice = await requestPromptChoice(['lesefluss', 'summary']);
        if (!choice) {
          toast.info('Aktion abgebrochen');
          setIsImprovingLesefluss(false);
          return;
        }
        await applyActivePrompt('lesefluss', choice.lesefluss ?? 'default');
        await applyActivePrompt('summary', choice.summary ?? 'default');
      }
      if (providedChoices) {
        await applyActivePrompt('lesefluss', providedChoices.lesefluss ?? 'default');
        await applyActivePrompt('summary', providedChoices.summary ?? 'default');
      }

      const leseflussToastId = toast.loading('Lese Fluss wird verbessert', {
        description: 'Der Text wird nun mit verbessertem Lesefluss erstellt...',
      });

      try {
        const result = await createLeseflussRun(
          activeKapitelId,
          selectedRun.id,
          contextKapitelIds,
          aufgabenstellung,
          model as 'gpt-5-nano' | 'gpt-5-mini' | 'gpt-5.2'
        );

        if (!result?.success) {
          const message = result?.error || 'Lese Fluss verbessern konnte nicht gestartet werden.';
          const lower = message.toLowerCase();

          if (lower.includes('sitzung')) {
            toast.error('Lese Fluss abgebrochen', {
              description: message,
              id: leseflussToastId,
            });
            handleAuthFailure();
            return;
          }

          if (lower.includes('fastapi-server')) {
            notifyServerDown(leseflussToastId);
            return;
          }

          toast.error('Lese Fluss fehlgeschlagen', {
            description: message,
            id: leseflussToastId,
          });
          return;
        }

        toast.success('Lese Fluss gestartet', {
          description: 'Der Text wird nun mit verbessertem Lesefluss erstellt.',
          id: leseflussToastId,
        });
      } catch (err: any) {
        console.error('Fehler beim Lese Fluss:', err);
        const message = err?.message || 'Unbekannter Fehler beim Lese Fluss';

        if (message.toLowerCase().includes('sitzung')) {
          toast.error('Lese Fluss abgebrochen', {
            description: message,
            id: leseflussToastId,
          });
          handleAuthFailure();
          return;
        }

        if (message.toLowerCase().includes('fastapi-server')) {
          notifyServerDown(leseflussToastId);
          return;
        }

        toast.error('Lese Fluss fehlgeschlagen', {
          description: message,
          id: leseflussToastId,
        });
      } finally {
        setIsImprovingLesefluss(false);
      }
    },
    [
      activeKapitelId,
      activeKapitel,
      ensureOpenAIAccess,
      handleAuthFailure,
      notifyServerDown,
      selectedRun,
      askOnEachProcess,
      requestPromptChoice,
      applyActivePrompt,
      isImprovingLesefluss,
    ]
  );

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
        <ProjektHeader
          projekt={projekt}
          projekte={projekte}
          onSwitchProjekt={handleSwitchProjekt}
          onCreateProjekt={handleCreateProjekt}
          onDeleteProjekt={(id, name) => setDeleteConfirm({ type: 'projekt', id, name })}
          isCreatingProjekt={isCreatingProjekt}
        />
        <KapitelNavigator
          kapiteln={kapiteln}
          activeKapitelId={activeKapitelId}
          onKapitelSelect={setActiveKapitelId}
          onAddKapitel={handleAddKapitel}
          onDeleteKapitel={(id, name) => setDeleteConfirm({ type: 'kapitel', id, name })}
          onEditKapitel={handleEditKapitel}
          addKapitelLoading={isCreatingKapitel}
          editKapitelLoading={isEditingKapitel}
        />
      </div>

      {/* Main Workspace */}
      <div className="flex-1 overflow-hidden flex">
        <div className="flex-1 overflow-hidden">
          {activeKapitel ? (
            isKapitelLoading ? (
              <KapitelWorkspaceSkeleton />
            ) : (
              <KapitelWorkspace
                kapitel={activeKapitel}
                assignedQuellen={assignedQuellen}
                runs={runs}
                selectedRun={selectedRun}
                allKapitels={kapiteln}
                onLoadAllRuns={() => {
                  setRunListLimit(MAX_RUN_HISTORY_LIMIT);
                  setAllRunsLoaded(true);
                }}
                allRunsLoaded={allRunsLoaded}
                onSelectRun={handleSelectRun}
                onOpenTextViewer={setTextViewerContent}
                onOpenProcessing={() => setProcessingDialogOpen(true)}
                onCombineTexts={handleCombineTexts}
                isCombining={isCombining}
                onToggleQuellenPanel={handleToggleQuellenPanel}
                onOpenShorten={() => setShortenDialogOpen(true)}
                onOpenLesefluss={() => setLeseflussDialogOpen(true)}
                onOpenLeseflussRefinement={() => setLeseflussRefinementDialogOpen(true)}
                onOpenCombinedRefinement={() => setCombinedRefinementDialogOpen(true)}
                onOpenShortenedRefinement={() => setShortenedRefinementDialogOpen(true)}
                onOpenResultRefinement={(quelleId, quelleName) => {
                  setResultRefinementTarget({ quelleId, quelleName });
                  setResultRefinementDialogOpen(true);
                }}
              />
            )
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
              onViewQuelle={handleViewQuelle}
              isAddingQuelle={isAddingQuelle}
              assigningQuelleIds={assigningQuelleIds}
              unassigningQuelleIds={unassigningQuelleIds}
              deletingQuelleIds={deletingQuelleIds}
            />
          ))}
      </div>

      <TextViewerModal content={textViewerContent} onClose={() => setTextViewerContent(null)} />
      <QuelleViewerModal
        quelle={quelleViewer}
        loading={quelleViewerLoading}
        open={!!quelleViewer}
        onOpenChange={(open) => {
          if (!open) setQuelleViewer(null);
        }}
      />

      {activeKapitel && (
        <ProcessingDialog
          open={processingDialogOpen}
          onOpenChange={setProcessingDialogOpen}
          kapitelTitle={activeKapitel.title}
          quellenCount={assignedQuellen.length}
          askOnEachProcess={askOnEachProcess}
          promptTemplates={promptTemplates}
          promptActive={promptActive}
          onProcess={handleProcess}
          isProcessing={isProcessingRun}
        />
      )}

      {activeKapitel && selectedRun && (
        <ShortenDialog
          open={shortenDialogOpen}
          onOpenChange={setShortenDialogOpen}
          allKapitels={kapiteln}
          currentKapitelId={activeKapitel.id}
          onShorten={handleShorten}
          askOnEachProcess={askOnEachProcess}
          promptTemplates={promptTemplates}
          promptActive={promptActive}
          isShortening={isShortening}
        />
      )}

      {activeKapitel && (
        <LeseflussDialog
          open={leseflussDialogOpen}
          onOpenChange={setLeseflussDialogOpen}
          allKapitels={kapiteln}
          currentKapitelId={activeKapitel.id}
          onLesefluss={handleLesefluss}
          askOnEachProcess={askOnEachProcess}
          promptTemplates={promptTemplates}
          promptActive={promptActive}
          isLeseflussLoading={isImprovingLesefluss}
        />
      )}

      {activeKapitel && selectedRun && (
        <CombinedRefinementDialog
          open={combinedRefinementDialogOpen}
          onOpenChange={setCombinedRefinementDialogOpen}
          kapitelId={activeKapitel.id}
          runId={selectedRun.id}
          runModel={selectedRun.model}
          kapitelLabel={`<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`}
          ensureOpenAIAccess={ensureOpenAIAccess}
          onAuthFailure={handleAuthFailure}
          onServerDown={notifyServerDown}
          onOpenTextViewer={setTextViewerContent}
        />
      )}

      {activeKapitel && selectedRun && (
        <ShortenedRefinementDialog
          open={shortenedRefinementDialogOpen}
          onOpenChange={setShortenedRefinementDialogOpen}
          kapitelId={activeKapitel.id}
          runId={selectedRun.id}
          kapitelLabel={`<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`}
          ensureOpenAIAccess={ensureOpenAIAccess}
          onAuthFailure={handleAuthFailure}
          onServerDown={notifyServerDown}
          onOpenTextViewer={setTextViewerContent}
        />
      )}

      {activeKapitel && selectedRun && (
        <LeseflussRefinementDialog
          open={leseflussRefinementDialogOpen}
          onOpenChange={setLeseflussRefinementDialogOpen}
          kapitelId={activeKapitel.id}
          runId={selectedRun.id}
          kapitelLabel={`<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`}
          ensureOpenAIAccess={ensureOpenAIAccess}
          onAuthFailure={handleAuthFailure}
          onServerDown={notifyServerDown}
          onOpenTextViewer={setTextViewerContent}
        />
      )}

      {activeKapitel && selectedRun && resultRefinementTarget && (
        <ResultRefinementDialog
          open={resultRefinementDialogOpen}
          onOpenChange={(open) => {
            setResultRefinementDialogOpen(open);
            if (!open) setResultRefinementTarget(null);
          }}
          kapitelId={activeKapitel.id}
          runId={selectedRun.id}
          quelleId={resultRefinementTarget.quelleId}
          quelleName={resultRefinementTarget.quelleName}
          kapitelLabel={`<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`}
          ensureOpenAIAccess={ensureOpenAIAccess}
          onAuthFailure={handleAuthFailure}
          onServerDown={notifyServerDown}
          onOpenTextViewer={setTextViewerContent}
        />
      )}

      {promptChooser && (
        <PromptSelectDialog
          open={!!promptChooser}
          stages={promptChooser.stages}
          templates={promptTemplates}
          active={promptActive}
          onConfirm={(choices) => {
            promptChooser.resolve(choices);
            setPromptChooser(null);
          }}
          onCancel={() => {
            promptChooser.resolve(null);
            setPromptChooser(null);
          }}
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
          } else if (deleteConfirm?.type === 'projekt') {
            handleDeleteProjekt(deleteConfirm.id);
          }
        }}
      />

      {/* Viewport Warning */}
      <ViewportWarning />
    </div>
  );
}

function buildPrompt(heading: string, topic: string, basicInfo?: string) {
  const prompt = `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`;

  const grundInfo = basicInfo?.trim()
    ? `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`
    : '';

  return `${prompt}${grundInfo}`;
}

// Status is now maintained via lightweight live listeners per Kapitel
