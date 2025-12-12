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
import { DeleteConfirmDialog } from './DeleteConfirmDialog';
import { DashboardSkeleton } from './DashboardSkeleton';
import { QuellenPanelSkeleton } from './QuellenPanelSkeleton';
import { KapitelWorkspaceSkeleton } from './KapitelWorkspaceSkeleton';
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
  type Unsubscribe,
  doc,
  updateDoc,
  serverTimestamp,
  addDoc,
  deleteDoc,
} from 'firebase/firestore';
import Cookies from 'js-cookie';
import { fetchOpenAIKeyStatus, type OpenAIKeyStatus } from '@/app/lib/api/openaiKeyClient';

const API_BASE_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://localhost:8000';
const RUN_HISTORY_LIMIT = 10;
const MAX_RUN_HISTORY_LIMIT = 200;

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

  const initialRunsForActive =
    initialRuns.length > 0
      ? initialRuns
      : initialKapitels.find((k) => k.id === initialActiveKapitelId)?.runs || [];
  const [fbRuns, setFbRuns] = useState<FirebaseKapitelRun[]>(initialRunsForActive);
  const keepInitialRunsRef = useRef(initialRunsForActive.length > 0);
  const [runListLimit, setRunListLimit] = useState<number>(RUN_HISTORY_LIMIT);
  const [allRunsLoaded, setAllRunsLoaded] = useState(false);
  const [isKapitelLoading, setIsKapitelLoading] = useState(initialRunsForActive.length === 0);
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const selectedRun = runs.find((r) => r.id === selectedRunId);
  const hasShownNoticeRef = useRef(false);
  const [keyStatus, setKeyStatus] = useState<OpenAIKeyStatus | null>(null);
  const [keyStatusLoading, setKeyStatusLoading] = useState(false);
  const keyNoticeShownRef = useRef(false);

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
    (toastId = 'fastapi-down') => {
      toast.error('Server nicht erreichbar', {
        description:
          'Der FastAPI-Server antwortet aktuell nicht. Das ist ein Server-Problem – du kannst nichts tun außer es später erneut zu versuchen.',
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

  const [showQuellenPanel, setShowQuellenPanel] = useState(false);
  const [textViewerContent, setTextViewerContent] = useState<{
    title: string;
    text: string;
  } | null>(null);
  const [quelleViewer, setQuelleViewer] = useState<Quelle | null>(null);
  const [processingDialogOpen, setProcessingDialogOpen] = useState(false);
  const [shortenDialogOpen, setShortenDialogOpen] = useState(false);
  const [leseflussDialogOpen, setLeseflussDialogOpen] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<{
    type: 'quelle' | 'kapitel' | 'projekt';
    id: string;
    name: string;
  } | null>(null);

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
    const q = query(runsRef, orderBy('index', 'desc'), limit(runListLimit));

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
              createdAt:
                data.createdAt?.toDate?.()?.toISOString() ||
                data.created_at?.toDate?.()?.toISOString() ||
                new Date().toISOString(),
              promptTemplateId: data.promptTemplateId,
              promptPayload: data.promptPayload,
              autoCombine: data.autoCombine ?? false,
              results: existing?.results || [],
              combined: existing?.combined || null,
              shortened: existing?.shortened || null,
              ueberschrift: data.ueberschrift || existing?.ueberschrift || '',
              thema: data.thema || data.instruction || existing?.thema || '',
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

  // Load data (combined/shortened/results) only for the selected run
  useEffect(() => {
    if (!user?.uid || !activeKapitelId || !selectedRunId) {
      return;
    }

    const db = getFirestore(firebaseApp);

    const combinedRef = collection(
      db,
      'users',
      user.uid,
      'kapitels',
      activeKapitelId,
      'runs',
      selectedRunId,
      'combined'
    );
    const shortenedRef = collection(
      db,
      'users',
      user.uid,
      'kapitels',
      activeKapitelId,
      'runs',
      selectedRunId,
      'shortened'
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

    const updateRunPartial = (partial: Partial<FirebaseKapitelRun>) => {
      setFbRuns((prev) =>
        prev.map((run) => (run.id === selectedRunId ? { ...run, ...partial } : run))
      );
    };
    const finishIfNeeded = () => {
      if (!settledOnce) {
        settledOnce = true;
        setIsKapitelLoading(false);
      }
    };

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
      updateRunPartial({ combined });
      hasData = hasData || !!combined;
      if (hasData) finishIfNeeded();
    });

    const shortenedUnsub = onSnapshot(shortenedRef, (shortenedSnap) => {
      let shortened: any = null;
      if (!shortenedSnap.empty) {
        const doc = shortenedSnap.docs[0];
        const data: any = doc.data();
        shortened = {
          id: doc.id,
          shortenedContent: data.shortened_content ?? data.shortenedContent ?? '',
          explanation: data.explanation ? {
            lengthDecision: data.explanation.length_decision ?? '',
            omittedTopics: data.explanation.omitted_topics ?? [],
            preservedFocus: data.explanation.preserved_focus ?? [],
            compressionNotes: data.explanation.compression_notes ?? '',
          } : undefined,
          originalLength: data.original_length ?? data.originalLength ?? 0,
          shortenedLength: data.shortened_length ?? data.shortenedLength ?? 0,
          usedKapitelIds: data.used_kapitel_ids ?? data.usedKapitelIds ?? [],
          model: data.model ?? '',
          cost: data.cost ?? 0,
          tokensUsed: data.tokens_used ?? data.tokensUsed ?? { input: 0, cachedInput: 0, output: 0 },
          createdAt:
            data.created_at?.toDate?.()?.toISOString() ||
            data.createdAt?.toDate?.()?.toISOString() ||
            new Date().toISOString(),
        };
      }
      updateRunPartial({ shortened });
      hasData = hasData || !!shortened;
      if (hasData) finishIfNeeded();
    });

    const leseflussRef = collection(
      db,
      'users',
      user.uid,
      'kapitels',
      activeKapitelId,
      'runs',
      selectedRunId,
      'lesefluss'
    );

    const leseflussUnsub = onSnapshot(leseflussRef, (leseflussSnap) => {
      let lesefluss: any = null;
      if (!leseflussSnap.empty) {
        const doc = leseflussSnap.docs[0];
        const data: any = doc.data();
        lesefluss = {
          id: doc.id,
          leseflussContent: data.lesefluss_content ?? data.leseflussContent ?? '',
          aufgabenstellung: data.aufgabenstellung ?? '',
          explanation: data.explanation ?? '',
          originalLength: data.original_length ?? data.originalLength ?? 0,
          leseflussLength: data.lesefluss_length ?? data.leseflussLength ?? 0,
          usedKapitelIds: data.used_kapitel_ids ?? data.usedKapitelIds ?? [],
          model: data.model ?? '',
          cost: data.cost ?? 0,
          tokensUsed: data.tokens_used ?? data.tokensUsed ?? { input: 0, cachedInput: 0, output: 0 },
          createdAt:
            data.created_at?.toDate?.()?.toISOString() ||
            data.createdAt?.toDate?.()?.toISOString() ||
            new Date().toISOString(),
        };
      }
      updateRunPartial({ lesefluss });
      hasData = hasData || !!lesefluss;
      if (hasData) finishIfNeeded();
    });

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

      updateRunPartial({ results });
      hasData = hasData || results.length > 0;
      if (hasData) finishIfNeeded();
      if (!hasData && resSnapshot.empty) {
        finishIfNeeded();
      }
    });

    return () => {
      combinedUnsub();
      shortenedUnsub();
      leseflussUnsub();
      resultsUnsub();
    };
  }, [user?.uid, activeKapitelId, selectedRunId]);

  // Live status per Kapitel (latest run only, minimal data)
  useEffect(() => {
    if (!user?.uid || kapiteln.length === 0) return;

    const db = getFirestore(firebaseApp);
    const runUnsubs: Unsubscribe[] = [];
    const combinedUnsubs: Map<string, Unsubscribe> = new Map();
    const kapitelIds = kapiteln.map((k) => k.id);

    const updateKapitelStatus = (
      kapitelId: string,
      status: 'nicht-verarbeitet' | 'in-bearbeitung' | 'fertig'
    ) => {
      setKapiteln((prev) =>
        prev.map((k) => {
          if (k.id !== kapitelId) return k;
          if (k.status === status) return k;
          return { ...k, status };
        })
      );
    };

    kapitelIds.forEach((kapitelId) => {
      const runsRef = collection(db, 'users', user.uid, 'kapitels', kapitelId, 'runs');
      const q = query(runsRef, orderBy('index', 'desc'), limit(1));

      const runUnsub = onSnapshot(q, (runSnap) => {
        const existing = combinedUnsubs.get(kapitelId);
        if (existing) {
          existing();
          combinedUnsubs.delete(kapitelId);
        }

        if (runSnap.empty) {
          updateKapitelStatus(kapitelId, 'nicht-verarbeitet');
          return;
        }

        const latestRunId = runSnap.docs[0].id;
        updateKapitelStatus(kapitelId, 'in-bearbeitung');

        const combinedRef = collection(
          db,
          'users',
          user.uid,
          'kapitels',
          kapitelId,
          'runs',
          latestRunId,
          'combined'
        );
        const combinedUnsub = onSnapshot(combinedRef, (combinedSnap) => {
          if (!combinedSnap.empty) {
            updateKapitelStatus(kapitelId, 'fertig');
          } else {
            updateKapitelStatus(kapitelId, 'in-bearbeitung');
          }
        });

        combinedUnsubs.set(kapitelId, combinedUnsub);
      });

      runUnsubs.push(runUnsub);
    });

    return () => {
      runUnsubs.forEach((u) => u());
      combinedUnsubs.forEach((u) => u());
    };
  }, [user?.uid, kapiteln.map((k) => k.id).join(',')]);

  // Live status per Kapitel (latest run only, minimal data)
  useEffect(() => {
    if (!user?.uid || kapiteln.length === 0) return;

    const db = getFirestore(firebaseApp);
    const runUnsubs: Unsubscribe[] = [];
    const combinedUnsubs: Map<string, Unsubscribe> = new Map();
    const kapitelIds = kapiteln.map((k) => k.id);

    const updateKapitelStatus = (
      kapitelId: string,
      status: 'nicht-verarbeitet' | 'in-bearbeitung' | 'fertig'
    ) => {
      setKapiteln((prev) => prev.map((k) => (k.id === kapitelId ? { ...k, status } : k)));
    };

    kapitelIds.forEach((kapitelId) => {
      const runsRef = collection(db, 'users', user.uid, 'kapitels', kapitelId, 'runs');
      const q = query(runsRef, orderBy('index', 'desc'), limit(1));

      const runUnsub = onSnapshot(q, (runSnap) => {
        const existing = combinedUnsubs.get(kapitelId);
        if (existing) {
          existing();
          combinedUnsubs.delete(kapitelId);
        }

        if (runSnap.empty) {
          updateKapitelStatus(kapitelId, 'nicht-verarbeitet');
          return;
        }

        const latestRunId = runSnap.docs[0].id;
        updateKapitelStatus(kapitelId, 'in-bearbeitung');

        const combinedRef = collection(
          db,
          'users',
          user.uid,
          'kapitels',
          kapitelId,
          'runs',
          latestRunId,
          'combined'
        );
        const combinedUnsub = onSnapshot(combinedRef, (combinedSnap) => {
          if (!combinedSnap.empty) {
            updateKapitelStatus(kapitelId, 'fertig');
          } else {
            updateKapitelStatus(kapitelId, 'in-bearbeitung');
          }
        });

        combinedUnsubs.set(kapitelId, combinedUnsub);
      });

      runUnsubs.push(runUnsub);
    });

    return () => {
      runUnsubs.forEach((u) => u());
      combinedUnsubs.forEach((u) => u());
    };
  }, [user?.uid, kapiteln.map((k) => k.id).join(',')]);

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
        toast.success('Projekt erstellt', { description: `"${name}" wurde erstellt.` });
      } catch (error: any) {
        console.error('Projekt erstellen fehlgeschlagen:', error);
        toast.error('Projekt konnte nicht erstellt werden', { description: error.message });
      }
    },
    [loadProjektData]
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
    async (name: string, text: string, imageFiles: File[] = []) => {
      const uploadingToast =
        imageFiles.length > 0
          ? toast.loading(`Lade ${imageFiles.length} Bild(er) hoch...`)
          : undefined;

      let imageMetadata: ImageMetadata[] = [];

      try {
        // Upload images to Storage first (client-side)
        if (imageFiles.length > 0) {
          const { uploadImagesToStorage } = await import('@/app/lib/firebase/storage');
          imageMetadata = await uploadImagesToStorage(user!.uid, imageFiles);
        }

        // Create Quelle with image metadata (not files)
        const result = await createQuelle(name, text, projekt.id, imageMetadata);

        if (uploadingToast) toast.dismiss(uploadingToast);

        if (result.success) {
          toast.success('Quelle hinzugefügt', {
            description: `"${name}" wurde erfolgreich erstellt${imageFiles.length > 0 ? ` mit ${imageFiles.length} Bild(ern)` : ''}.`,
          });
          // Optimistically update UI
          const newQuelle: Quelle = {
            id: result.id!,
            name,
            text,
            projektId: projekt.id,
            createdAt: new Date(),
            images: result.imageUrls || [],
          };
          setQuellen((prev) => [...prev, newQuelle]);
        } else {
          toast.error('Fehler', { description: result.error });

          // Cleanup uploaded images if Firestore creation failed
          if (imageMetadata.length > 0) {
            const { deleteImagesFromStorage } = await import('@/app/lib/firebase/storage');
            await deleteImagesFromStorage(imageMetadata.map(img => img.path));
          }
        }
      } catch (error) {
        if (uploadingToast) toast.dismiss(uploadingToast);
        toast.error('Upload fehlgeschlagen', {
          description: error instanceof Error ? error.message : 'Unbekannter Fehler',
        });

        // Cleanup uploaded images on error
        if (imageMetadata.length > 0) {
          const { deleteImagesFromStorage } = await import('@/app/lib/firebase/storage');
          await deleteImagesFromStorage(imageMetadata.map(img => img.path));
        }
      }
    },
    [projekt.id, user]
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

      const quelle = quellen.find((q) => q.id === quelleId);

      try {
        await persistKapitelQuellenClient(activeKapitelId, newQuelleIds);
        toast.success('Quelle zugewiesen', {
          description: quelle ? `"${quelle.name}" wurde dem Kapitel hinzugefügt.` : undefined,
        });
      } catch (clientErr) {
        // Fallback to server action
        const result = await updateKapitelQuellen(activeKapitelId, newQuelleIds);
        if (!result.success) {
          setKapiteln((prev) =>
            prev.map((k) => (k.id === activeKapitelId ? { ...k, assignedQuellenIds: prevQuelleIds } : k))
          );
          toast.error('Fehler', { description: result.error });
        } else {
          toast.success('Quelle zugewiesen', {
            description: quelle ? `"${quelle.name}" wurde dem Kapitel hinzugefügt.` : undefined,
          });
        }
      }
    },
    [activeKapitelId, kapiteln, persistKapitelQuellenClient, quellen]
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

      const quelle = quellen.find((q) => q.id === quelleId);

      try {
        await persistKapitelQuellenClient(activeKapitelId, newQuelleIds);
        toast.success('Quelle entfernt', {
          description: quelle ? `"${quelle.name}" wurde vom Kapitel entfernt.` : undefined,
        });
      } catch (clientErr) {
        const result = await updateKapitelQuellen(activeKapitelId, newQuelleIds);
        if (!result.success) {
          setKapiteln((prev) =>
            prev.map((k) => (k.id === activeKapitelId ? { ...k, assignedQuellenIds: prevQuelleIds } : k))
          );
          toast.error('Fehler', { description: result.error });
        } else {
          toast.success('Quelle entfernt', {
            description: quelle ? `"${quelle.name}" wurde vom Kapitel entfernt.` : undefined,
          });
        }
      }
    },
    [activeKapitelId, kapiteln, persistKapitelQuellenClient, quellen]
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
      const result = await createKapitel(title, [], null, nummer, projekt.id);
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
        handleSelectRun(result.runId);
        setProcessingDialogOpen(false);

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
                    id: 'processing',
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
                  id: 'processing',
                });
                handleAuthFailure();
                return;
              }

              if (err instanceof TypeError || (typeof status === 'number' && status >= 500)) {
                serverUnavailable = true;
                queue.length = 0;
                notifyServerDown('processing');
                return;
              }

              console.error(`Error processing Quelle ${nextQuelle?.id}:`, err);
              toast.error('Fehler bei einer Quelle', {
                description: err.message || 'Unbekannter Fehler beim Verarbeiten der Quelle',
              });
            }
          }
        };

        await Promise.all(Array.from({ length: concurrency }, () => worker()));

        if (authFailed || serverUnavailable) {
          return;
        }

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
    [activeKapitelId, activeKapitel, ensureOpenAIAccess, handleAuthFailure, handleSelectRun, notifyServerDown, quellen]
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
        if (response.status === 401) {
          toast.error('Kombination abgebrochen', {
            description: 'Bitte melde dich erneut an.',
            id: 'combine',
          });
          handleAuthFailure();
          return;
        }

        if (response.status >= 500) {
          notifyServerDown('combine');
          return;
        }

        const error = await response.json().catch(() => ({}));
        const err: any = new Error(error.detail || 'Fehler beim Kombinieren');
        err.status = response.status;
        throw err;
      }

      toast.success('Kombination gestartet', {
        description: 'Die Texte werden nun zusammengeführt.',
        id: 'combine',
      });
    } catch (err: any) {
      if (err instanceof TypeError) {
        notifyServerDown('combine');
        return;
      }

      if (err?.status === 401) {
        handleAuthFailure();
        return;
      }

      console.error('Fehler beim Kombinieren:', err);
      toast.error('Combine fehlgeschlagen', {
        description: err.message || 'Unbekannter Fehler beim Kombinieren',
        id: 'combine',
      });
    }
  }, [activeKapitelId, ensureOpenAIAccess, handleAuthFailure, notifyServerDown, selectedRun]);

  const handleShorten = useCallback(
    async (contextKapitelIds: string[], model: string) => {
      if (!activeKapitel || !selectedRun) return;

      if (!(await ensureOpenAIAccess())) return;

      if (contextKapitelIds.length === 0) {
        toast.error('Keine Kontextkapitel ausgewählt', {
          description: 'Wähle mindestens ein Kapitel als Kontext aus.',
        });
        return;
      }

      toast.loading('Text wird gekürzt', {
        description: 'Der Text wird mit Hilfe der ausgewählten Kapitel gekürzt...',
        id: 'shortening',
      });

      try {
        const result = await createShortenRun(
          activeKapitelId,
          selectedRun.id,
          contextKapitelIds,
          model as 'gpt-5-nano' | 'gpt-5-mini' | 'gpt-5.1'
        );

        if (!result?.success) {
          const message = result?.error || 'Kürzung konnte nicht gestartet werden.';
          const lower = message.toLowerCase();

          if (lower.includes('sitzung')) {
            toast.error('Kürzung abgebrochen', {
              description: message,
              id: 'shortening',
            });
            handleAuthFailure();
            return;
          }

          if (lower.includes('fastapi-server')) {
            notifyServerDown('shortening');
            return;
          }

          toast.error('Kürzung fehlgeschlagen', {
            description: message,
            id: 'shortening',
          });
          return;
        }

        toast.success('Kürzung gestartet', {
          description: 'Der Text wird nun gekürzt und entdupliziert.',
          id: 'shortening',
        });
      } catch (err: any) {
        console.error('Fehler beim Kürzen:', err);
        const message = err?.message || 'Unbekannter Fehler beim Kürzen';

        if (message.toLowerCase().includes('sitzung')) {
          toast.error('Kürzung abgebrochen', {
            description: message,
            id: 'shortening',
          });
          handleAuthFailure();
          return;
        }

        if (message.toLowerCase().includes('fastapi-server')) {
          notifyServerDown('shortening');
          return;
        }

        toast.error('Kürzung fehlgeschlagen', {
          description: message,
          id: 'shortening',
        });
      }
    },
    [activeKapitelId, activeKapitel, ensureOpenAIAccess, handleAuthFailure, notifyServerDown, selectedRun]
  );

  const handleLesefluss = useCallback(
    async (contextKapitelIds: string[], aufgabenstellung: string, model: string) => {
      if (!activeKapitel || !selectedRun) return;

      if (!(await ensureOpenAIAccess())) return;

      if (contextKapitelIds.length === 0) {
        toast.error('Keine Kontextkapitel ausgewählt', {
          description: 'Wähle mindestens ein Kapitel als Kontext aus.',
        });
        return;
      }

      toast.loading('Lese Fluss wird verbessert', {
        description: 'Der Text wird nun mit verbessertem Lesefluss erstellt...',
        id: 'lesefluss',
      });

      try {
        const result = await createLeseflussRun(
          activeKapitelId,
          selectedRun.id,
          contextKapitelIds,
          aufgabenstellung,
          model as 'gpt-5-nano' | 'gpt-5-mini' | 'gpt-5.1'
        );

        if (!result?.success) {
          const message = result?.error || 'Lese Fluss verbessern konnte nicht gestartet werden.';
          const lower = message.toLowerCase();

          if (lower.includes('sitzung')) {
            toast.error('Lese Fluss abgebrochen', {
              description: message,
              id: 'lesefluss',
            });
            handleAuthFailure();
            return;
          }

          if (lower.includes('fastapi-server')) {
            notifyServerDown('lesefluss');
            return;
          }

          toast.error('Lese Fluss fehlgeschlagen', {
            description: message,
            id: 'lesefluss',
          });
          return;
        }

        toast.success('Lese Fluss gestartet', {
          description: 'Der Text wird nun mit verbessertem Lesefluss erstellt.',
          id: 'lesefluss',
        });
      } catch (err: any) {
        console.error('Fehler beim Lese Fluss:', err);
        const message = err?.message || 'Unbekannter Fehler beim Lese Fluss';

        if (message.toLowerCase().includes('sitzung')) {
          toast.error('Lese Fluss abgebrochen', {
            description: message,
            id: 'lesefluss',
          });
          handleAuthFailure();
          return;
        }

        if (message.toLowerCase().includes('fastapi-server')) {
          notifyServerDown('lesefluss');
          return;
        }

        toast.error('Lese Fluss fehlgeschlagen', {
          description: message,
          id: 'lesefluss',
        });
      }
    },
    [activeKapitelId, activeKapitel, ensureOpenAIAccess, handleAuthFailure, notifyServerDown, selectedRun]
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
        />
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
                onToggleQuellenPanel={handleToggleQuellenPanel}
                onOpenShorten={() => setShortenDialogOpen(true)}
                onOpenLesefluss={() => setLeseflussDialogOpen(true)}
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
              onViewQuelle={(quelle) => setQuelleViewer(quelle)}
            />
          ))}
      </div>

      <TextViewerModal content={textViewerContent} onClose={() => setTextViewerContent(null)} />
      <QuelleViewerModal
        quelle={quelleViewer}
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
          onProcess={handleProcess}
        />
      )}

      {activeKapitel && selectedRun && (
        <ShortenDialog
          open={shortenDialogOpen}
          onOpenChange={setShortenDialogOpen}
          kapitel={activeKapitel}
          selectedRun={selectedRun}
          allKapitels={kapiteln}
          onShorten={handleShorten}
        />
      )}

      {activeKapitel && (
        <LeseflussDialog
          open={leseflussDialogOpen}
          onOpenChange={setLeseflussDialogOpen}
          kapitel={activeKapitel}
          selectedRun={selectedRun}
          allKapitels={kapiteln}
          onLesefluss={handleLesefluss}
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

// Status is now maintained via lightweight live listeners per Kapitel
