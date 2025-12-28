'use server';

import { getFirestoreForUser } from '@/app/lib/firebase/serverApp';
import { requireAuth, type AuthUser } from '@/app/lib/auth/server-auth';
import { revalidatePath } from 'next/cache';
import { cookies } from 'next/headers';
import {
  addDoc,
  doc,
  getDoc,
  getDocs,
  limit,
  orderBy,
  query,
  serverTimestamp,
  updateDoc,
  where,
  type CollectionReference,
  type DocumentData,
  type DocumentReference,
  type Firestore,
} from 'firebase/firestore';
import {
  artifactsCol,
  artifactDoc,
  combinedGroupsCol,
  resultsCol,
  runsCol,
  summariesCol,
  kapitelDoc,
  kapitelsCol,
} from '@/app/lib/firestore/refs';

export type Usage = {
  inputTokens: number;
  cachedInputTokens: number;
  outputTokens: number;
  reasoningTokens: number;
  totalTokens: number;
};

export type RefinementMeta = {
  rootVersionId: 'root';
  activeVersionId: string;
  maxDepth: number;
  costTotalUsd: number;
  initializedAt: string;
  selectedAt?: string | null;
};

export type KapitelRunResult = {
  quelleId: string;
  userInput: string;
  content: string;
  hasContent: boolean;
  status?: 'running' | 'success' | 'error' | 'no-content';
  model: string;
  usage: Usage;
  costUsd: number;
  refinement: RefinementMeta;
  createdAt: string;
  updatedAt?: string;
};

export type CombinedResult = {
  id: 'combined';
  content: string;
  status?: 'running' | 'success' | 'error';
  sourceQuelleIds: string[];
  heading: string;
  topic: string;
  model: string;
  usage: Usage;
  costUsd: number;
  createdAt: string;
  updatedAt?: string;
  refinement: RefinementMeta;
};

export type IntermediateGroupResult = {
  id: string;
  groupNumber: number;
  content: string;
  sourceQuelleIds: string[];
  heading: string;
  topic: string;
  model: string;
  usage: Usage;
  costUsd: number;
  createdAt: string;
  updatedAt?: string;
};

export type ShortenedResult = {
  id: 'shortened';
  content: string;
  status?: 'running' | 'success' | 'error';
  originalLength: number;
  shortenedLength: number;
  usedKapitelIds: string[];
  model: string;
  usage: Usage;
  costUsd: number;
  createdAt: string;
  updatedAt?: string;
  refinement: RefinementMeta;
};

export type SummaryResult = {
  id: string;
  content: string;
  sourceKapitelId: string;
  sourceRunId: string;
  sourceType: 'combined' | 'shortened';
  originalLength: number;
  summaryLength: number;
  model: string;
  costUsd: number;
  usage: Pick<Usage, 'inputTokens' | 'outputTokens' | 'totalTokens'>;
  createdAt: string;
};

export type LeseflussResult = {
  id: 'lesefluss';
  content: string;
  status?: 'running' | 'success' | 'error';
  aufgabenstellung: string;
  originalLength?: number;
  leseflussLength: number;
  usedKapitelIds: string[];
  model: string;
  usage: Usage;
  costUsd: number;
  createdAt: string;
  updatedAt?: string;
  refinement: RefinementMeta;
};

export type KapitelRun = {
  id: string;
  index: number;
  instruction: string;
  model: string;
  createdAt: string;
  updatedAt?: string;
  results: KapitelRunResult[];
  artifacts?: {
    combined?: CombinedResult | null;
    shortened?: ShortenedResult | null;
    lesefluss?: LeseflussResult | null;
  };
  promptTemplateId?: string;
  promptPayload?: Record<string, unknown>;
  autoCombine: boolean;
  ueberschrift?: string;
  thema?: string;
  grundlegendeInformationen?: string | null;
  artifactsStatus?: {
    combined: 'empty' | 'running' | 'success' | 'error';
    shortened: 'empty' | 'running' | 'success' | 'error';
    lesefluss: 'empty' | 'running' | 'success' | 'error';
  };
  resultsExpectedCount?: number;
  resultsCompletedCount?: number;
  resultsWithContentCount?: number;
  lastResultAt?: string | null;
  lastActivityAt?: string | null;
};

export type Kapitel = {
  id: string;
  title: string;
  projektId: string;
  nummer: string;
  createdAt: string;
  updatedAt?: string;
  archived: boolean;
  archivedAt?: string;
  quelleIds: string[];
  parentId: string | null;
  order: number;
  latestRun?: {
    runId: string;
    index: number;
    status: 'none' | 'running' | 'done';
    updatedAt: string;
  };
  runs?: KapitelRun[];
};

type ActionContext = {
  user?: AuthUser;
  db?: Firestore;
};

async function getContext(ctx?: ActionContext) {
  const user = ctx?.user ?? (await requireAuth());
  const db = ctx?.db ?? (await getFirestoreForUser());
  return { user, db };
}

function toIso(value: unknown): string {
  if (!value) return new Date().toISOString();
  if (value instanceof Date) return value.toISOString();
  if (typeof value === 'string') {
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? new Date().toISOString() : d.toISOString();
  }
  if (typeof value === 'object' && 'toDate' in value && typeof (value as { toDate?: unknown }).toDate === 'function') {
    const d = (value as { toDate: () => Date }).toDate();
    return d instanceof Date ? d.toISOString() : new Date().toISOString();
  }
  return new Date().toISOString();
}

function normalizeUsage(u: unknown): Usage {
  const usage = u && typeof u === 'object' ? (u as Record<string, unknown>) : {};
  return {
    inputTokens: Number(usage.inputTokens ?? 0),
    cachedInputTokens: Number(usage.cachedInputTokens ?? 0),
    outputTokens: Number(usage.outputTokens ?? 0),
    reasoningTokens: Number(usage.reasoningTokens ?? 0),
    totalTokens: Number(usage.totalTokens ?? 0),
  };
}

function normalizeRefinement(r: unknown): RefinementMeta {
  const refinement = r && typeof r === 'object' ? (r as Record<string, unknown>) : {};
  return {
    rootVersionId: 'root',
    activeVersionId: String(refinement.activeVersionId ?? 'root'),
    maxDepth: Number(refinement.maxDepth ?? 4),
    costTotalUsd: Number(refinement.costTotalUsd ?? 0),
    initializedAt: toIso(refinement.initializedAt),
    selectedAt: refinement.selectedAt ? toIso(refinement.selectedAt) : null,
  };
}

function normalizeRunStatus(status: unknown): 'none' | 'running' | 'done' {
  return status === 'running' || status === 'done' || status === 'none' ? status : 'none';
}

function normalizeSummarySourceType(sourceType: unknown): 'combined' | 'shortened' {
  return sourceType === 'shortened' ? 'shortened' : 'combined';
}

function normalizeRunModel(model: unknown): 'gpt-5-nano' | 'gpt-5-mini' | 'gpt-5.2' {
  const m = String(model ?? '').trim();
  return m === 'gpt-5-nano' || m === 'gpt-5-mini' || m === 'gpt-5.2' ? m : 'gpt-5-nano';
}

function normalizeResultDocStatus(status: unknown): KapitelRunResult['status'] {
  return status === 'running' || status === 'success' || status === 'error' || status === 'no-content' ? status : undefined;
}

function normalizeArtifactDocStatus(status: unknown): 'running' | 'success' | 'error' | undefined {
  return status === 'running' || status === 'success' || status === 'error' ? status : undefined;
}

async function fetchFastApi(path: string, payload: unknown) {
  await requireAuth();
  const apiBaseUrl = process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://localhost:8000';
  const cookieStore = await cookies();
  const authToken = cookieStore.get('__session')?.value;
  if (!authToken) return { success: false, error: 'Deine Sitzung ist abgelaufen. Bitte melde dich erneut an.' };

  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${authToken}` },
      body: JSON.stringify(payload),
    });
  } catch {
    return {
      success: false,
      error: 'FastAPI-Server ist nicht erreichbar. Das ist ein Server-Problem - bitte später erneut versuchen.',
    };
  }

  if (response.status === 401) return { success: false, error: 'Deine Sitzung ist abgelaufen. Bitte melde dich erneut an.' };
  if (response.status >= 500)
    return { success: false, error: 'FastAPI-Server antwortet gerade nicht. Das liegt nicht an dir - versuche es später erneut.' };

  if (!response.ok) {
    const errorText = await response.text();
    return { success: false, error: errorText || 'Request fehlgeschlagen.' };
  }

  const data = await response.json().catch(() => null);
  revalidatePath('/dashboard');
  return { success: true, data };
}

async function checkCircularReference(db: Firestore, userId: string, kapitelId: string, targetParentId: string | null) {
  if (!targetParentId) return false;
  let currentId: string | null = targetParentId;
  const visited = new Set<string>([kapitelId]);
  while (currentId) {
    if (visited.has(currentId)) return true;
    visited.add(currentId);
    const parentSnap = await getDoc(kapitelDoc(db, userId, currentId));
    if (!parentSnap.exists()) break;
    const parentData = parentSnap.data() as DocumentData;
    currentId = (parentData.parentId as string | null | undefined) ?? null;
  }
  return false;
}

async function getKapitelDepth(db: Firestore, userId: string, kapitelId: string): Promise<number> {
  let depth = 0;
  let currentId: string | null = kapitelId;
  while (currentId) {
    const snap = await getDoc(kapitelDoc(db, userId, currentId));
    if (!snap.exists()) break;
    const data = snap.data() as DocumentData;
    currentId = (data.parentId as string | null | undefined) ?? null;
    depth += 1;
    if (depth > 20) break;
  }
  return depth - 1;
}

async function archiveKapitelInternal(
  db: Firestore,
  userId: string,
  kapitelId: string,
  strategy: 'promote' | 'cascade'
) {
  const ref = kapitelDoc(db, userId, kapitelId);
  const snap = await getDoc(ref);
  if (!snap.exists()) throw new Error('Kapitel not found');
  const data = snap.data() as DocumentData;
  const parentId = (data.parentId as string | null | undefined) ?? null;

  const childrenSnapshot = await getDocs(
    query(kapitelsCol(db, userId), where('parentId', '==', kapitelId), where('archived', '==', false))
  );

  if (strategy === 'cascade') {
    for (const child of childrenSnapshot.docs) {
      await archiveKapitelInternal(db, userId, child.id, 'cascade');
    }
  } else {
    for (const child of childrenSnapshot.docs) {
      await updateDoc(kapitelDoc(db, userId, child.id) as unknown as DocumentReference<DocumentData>, {
        parentId,
        updatedAt: serverTimestamp(),
      });
    }
  }

  await updateDoc(ref as unknown as DocumentReference<DocumentData>, {
    archived: true,
    archivedAt: serverTimestamp(),
    updatedAt: serverTimestamp(),
  });
}

export async function createKapitel(title: string, quelleIds: string[], parentId: string | null, nummer: string, projektId: string) {
  try {
    const user = await requireAuth();
    if (!user) return { success: false, error: 'Not authenticated' };
    const db = await getFirestoreForUser();

    if (parentId) {
      const parentSnap = await getDoc(kapitelDoc(db, user.uid, parentId));
      if (!parentSnap.exists()) return { success: false, error: 'Parent Kapitel not found' };
      const parentDepth = await getKapitelDepth(db, user.uid, parentId);
      if (parentDepth >= 4) return { success: false, error: 'Maximum nesting depth (5 levels) would be exceeded' };
    }

    const docRef = await addDoc(kapitelsCol(db, user.uid) as unknown as CollectionReference<DocumentData>, {
      projektId,
      title,
      nummer: nummer || '1',
      parentId: parentId ?? null,
      order: Date.now(),
      quelleIds,
      createdAt: serverTimestamp(),
      updatedAt: serverTimestamp(),
      archived: false,
    });

    revalidatePath('/dashboard');
    return { success: true, id: docRef.id };
  } catch (error: unknown) {
    console.error('Error creating Kapitel:', error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
  }
}

export async function updateKapitelQuellen(kapitelId: string, quelleIds: string[]) {
  try {
    const user = await requireAuth();
    if (!user) return { success: false, error: 'Not authenticated' };
    const db = await getFirestoreForUser();
    const ref = kapitelDoc(db, user.uid, kapitelId);
    const snap = await getDoc(ref);
    if (!snap.exists()) throw new Error('Kapitel not found');
    await updateDoc(ref as unknown as DocumentReference<DocumentData>, { quelleIds, updatedAt: serverTimestamp() });
    revalidatePath('/dashboard');
    return { success: true };
  } catch (error: unknown) {
    console.error('Error updating Kapitel Quellen:', error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
  }
}

export async function updateKapitelParent(kapitelId: string, newParentId: string | null) {
  try {
    const user = await requireAuth();
    if (!user) return { success: false, error: 'Not authenticated' };
    const db = await getFirestoreForUser();
    const ref = kapitelDoc(db, user.uid, kapitelId);
    const snap = await getDoc(ref);
    if (!snap.exists()) return { success: false, error: 'Kapitel not found' };

    if (newParentId) {
      const hasCircular = await checkCircularReference(db, user.uid, kapitelId, newParentId);
      if (hasCircular) return { success: false, error: 'Cannot set parent: would create circular reference' };
      const parentSnap = await getDoc(kapitelDoc(db, user.uid, newParentId));
      if (!parentSnap.exists()) return { success: false, error: 'Parent Kapitel not found' };
      const parentDepth = await getKapitelDepth(db, user.uid, newParentId);
      if (parentDepth >= 4) return { success: false, error: 'Maximum nesting depth (5 levels) would be exceeded' };
    }

    await updateDoc(ref as unknown as DocumentReference<DocumentData>, {
      parentId: newParentId ?? null,
      order: Date.now(),
      updatedAt: serverTimestamp(),
    });
    revalidatePath('/dashboard');
    return { success: true };
  } catch (error: unknown) {
    console.error('Error updating Kapitel parent:', error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
  }
}

export async function updateKapitelTitle(kapitelId: string, title: string, nummer: string) {
  try {
    const user = await requireAuth();
    if (!user) return { success: false, error: 'Not authenticated' };
    const db = await getFirestoreForUser();
    const ref = kapitelDoc(db, user.uid, kapitelId);
    const snap = await getDoc(ref);
    if (!snap.exists()) throw new Error('Kapitel not found');
    await updateDoc(ref as unknown as DocumentReference<DocumentData>, {
      title,
      nummer,
      updatedAt: serverTimestamp(),
    });
    revalidatePath('/dashboard');
    return { success: true };
  } catch (error: unknown) {
    console.error('Error updating Kapitel title:', error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
  }
}

export async function deleteKapitel(kapitelId: string, deleteStrategy: 'promote' | 'cascade' = 'promote') {
  try {
    const user = await requireAuth();
    if (!user) return { success: false, error: 'Not authenticated' };
    const db = await getFirestoreForUser();
    await archiveKapitelInternal(db, user.uid, kapitelId, deleteStrategy);
    revalidatePath('/dashboard');
    return { success: true };
  } catch (error: unknown) {
    console.error('Error deleting Kapitel:', error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
  }
}

export async function createKapitelRun(
  kapitelId: string,
  instruction: string,
  model: string,
  options?: {
    promptTemplateId?: string;
    promptPayload?: Record<string, unknown>;
    autoCombine?: boolean;
    grundlegendeInformationen?: string;
    ueberschrift?: string;
    thema?: string;
  }
) {
  try {
    const user = await requireAuth();
    if (!user) return { success: false, error: 'Not authenticated' };
    const db = await getFirestoreForUser();

    const kapitelRef = kapitelDoc(db, user.uid, kapitelId);
    const kapitelSnap = await getDoc(kapitelRef);
    if (!kapitelSnap.exists()) return { success: false, error: 'Kapitel not found' };
    const kapitelData = kapitelSnap.data() as DocumentData;

    const projektId = String(kapitelData.projektId ?? 'default');
    const quelleIds: string[] = Array.isArray(kapitelData.quelleIds) ? kapitelData.quelleIds : [];

    const runsRef = runsCol(db, user.uid, kapitelId);
    const lastRunSnapshot = await getDocs(query(runsRef, orderBy('index', 'desc'), limit(1)));
    const lastIndex = lastRunSnapshot.empty ? 0 : Number(lastRunSnapshot.docs[0].data().index ?? 0);
    const nextIndex = lastIndex + 1;

    const runDocRef = await addDoc(runsRef as unknown as CollectionReference<DocumentData>, {
      projektId,
      index: nextIndex,
      instruction,
      model,
      createdAt: serverTimestamp(),
      updatedAt: serverTimestamp(),
      archived: false,
      autoCombine: options?.autoCombine ?? false,
      promptTemplateId: options?.promptTemplateId,
      promptPayload: options?.promptPayload,
      grundlegendeInformationen: options?.grundlegendeInformationen || null,
      ueberschrift: options?.ueberschrift || null,
      thema: options?.thema || null,
      resultsExpectedCount: quelleIds.length,
      resultsCompletedCount: 0,
      resultsWithContentCount: 0,
      // If auto-combine is enabled, show the combined stage as "running" immediately,
      // even while Quellen results are still processing (the server will flip to success/error later).
      artifactsStatus: {
        combined: options?.autoCombine ? 'running' : 'empty',
        shortened: 'empty',
        lesefluss: 'empty',
      },
      lastActivityAt: serverTimestamp(),
    });

    await updateDoc(kapitelRef as unknown as DocumentReference<DocumentData>, {
      latestRun: { runId: runDocRef.id, index: nextIndex, status: 'running', updatedAt: serverTimestamp() },
      updatedAt: serverTimestamp(),
    });

    revalidatePath('/dashboard');
    return { success: true, runId: runDocRef.id, index: nextIndex };
  } catch (error: unknown) {
    console.error('Error creating Kapitel run:', error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
  }
}

export async function getKapitelRuns(kapitelId: string, runLimit = 10, ctx?: ActionContext): Promise<KapitelRun[]> {
  try {
    const { user, db } = await getContext(ctx);
    if (!user) throw new Error('Not authenticated');

    const runsSnapshot = await getDocs(
      query(runsCol(db, user.uid, kapitelId), where('archived', '==', false), orderBy('index', 'desc'), limit(runLimit))
    );

    const runs: KapitelRun[] = await Promise.all(
      runsSnapshot.docs.map(async (runSnap) => {
        const runData = runSnap.data() as DocumentData;

        const [resultsSnapshot, artifactsSnapshot] = await Promise.all([
          getDocs(resultsCol(db, user.uid, kapitelId, runSnap.id)),
          getDocs(artifactsCol(db, user.uid, kapitelId, runSnap.id)),
        ]);

        const results: KapitelRunResult[] = resultsSnapshot.docs.map((d) => {
          const r = d.data() as DocumentData;
          return {
            quelleId: String(r.quelleId ?? d.id),
            userInput: String(r.userInput ?? ''),
            content: String(r.content ?? ''),
            hasContent: Boolean(r.hasContent),
            status: normalizeResultDocStatus(r.status),
            model: String(r.model ?? ''),
            usage: normalizeUsage(r.usage),
            costUsd: Number(r.costUsd ?? 0),
            refinement: normalizeRefinement(r.refinement),
            createdAt: toIso(r.createdAt),
            updatedAt: r.updatedAt ? toIso(r.updatedAt) : undefined,
          };
        });

        let combined: CombinedResult | null = null;
        let shortened: ShortenedResult | null = null;
        let lesefluss: LeseflussResult | null = null;

        for (const d of artifactsSnapshot.docs) {
          const a = d.data() as DocumentData;
          const artifactId = String(a.artifactId ?? d.id);
           if (artifactId === 'combined') {
             combined = {
               id: 'combined',
               content: String(a.content ?? ''),
               status: normalizeArtifactDocStatus(a.status),
               sourceQuelleIds: Array.isArray(a.sourceQuelleIds) ? a.sourceQuelleIds : [],
               heading: String(a.heading ?? ''),
               topic: String(a.topic ?? ''),
               model: String(a.model ?? ''),
               usage: normalizeUsage(a.usage),
              costUsd: Number(a.costUsd ?? 0),
              refinement: normalizeRefinement(a.refinement),
              createdAt: toIso(a.createdAt),
              updatedAt: a.updatedAt ? toIso(a.updatedAt) : undefined,
            };
           } else if (artifactId === 'shortened') {
              shortened = {
                id: 'shortened',
                content: String(a.content ?? ''),
                status: normalizeArtifactDocStatus(a.status),
               originalLength: Number(a.originalLength ?? 0),
               shortenedLength: Number(a.shortenedLength ?? 0),
               usedKapitelIds: Array.isArray(a.usedKapitelIds) ? a.usedKapitelIds : [],
               model: String(a.model ?? ''),
              usage: normalizeUsage(a.usage),
              costUsd: Number(a.costUsd ?? 0),
              refinement: normalizeRefinement(a.refinement),
              createdAt: toIso(a.createdAt),
              updatedAt: a.updatedAt ? toIso(a.updatedAt) : undefined,
            };
           } else if (artifactId === 'lesefluss') {
              lesefluss = {
                id: 'lesefluss',
                content: String(a.content ?? ''),
                status: normalizeArtifactDocStatus(a.status),
                aufgabenstellung: String(a.aufgabenstellung ?? ''),
                originalLength: typeof a.originalLength === 'number' ? a.originalLength : undefined,
                leseflussLength: Number(a.leseflussLength ?? 0),
               usedKapitelIds: Array.isArray(a.usedKapitelIds) ? a.usedKapitelIds : [],
               model: String(a.model ?? ''),
              usage: normalizeUsage(a.usage),
              costUsd: Number(a.costUsd ?? 0),
              refinement: normalizeRefinement(a.refinement),
              createdAt: toIso(a.createdAt),
              updatedAt: a.updatedAt ? toIso(a.updatedAt) : undefined,
            };
          }
        }

        return {
          id: runSnap.id,
          index: Number(runData.index ?? 0),
          instruction: String(runData.instruction ?? ''),
          model: String(runData.model ?? ''),
          createdAt: toIso(runData.createdAt),
          updatedAt: runData.updatedAt ? toIso(runData.updatedAt) : undefined,
          results,
          artifacts: { combined, shortened, lesefluss },
          promptTemplateId: runData.promptTemplateId,
          promptPayload: runData.promptPayload,
          autoCombine: Boolean(runData.autoCombine),
          ueberschrift: typeof runData.ueberschrift === 'string' ? runData.ueberschrift : undefined,
          thema: typeof runData.thema === 'string' ? runData.thema : undefined,
          grundlegendeInformationen:
            typeof runData.grundlegendeInformationen === 'string' ? runData.grundlegendeInformationen : null,
          artifactsStatus: runData.artifactsStatus,
          resultsExpectedCount: typeof runData.resultsExpectedCount === 'number' ? runData.resultsExpectedCount : undefined,
          resultsCompletedCount:
            typeof runData.resultsCompletedCount === 'number' ? runData.resultsCompletedCount : undefined,
          resultsWithContentCount:
            typeof runData.resultsWithContentCount === 'number' ? runData.resultsWithContentCount : undefined,
          lastResultAt: runData.lastResultAt ? toIso(runData.lastResultAt) : null,
          lastActivityAt: runData.lastActivityAt ? toIso(runData.lastActivityAt) : null,
        };
      })
    );

    return runs;
  } catch (error: unknown) {
    console.error('Error fetching Kapitel runs:', error);
    return [];
  }
}

export async function getUserKapitels(
  projektId: string,
  withRuns = false,
  runLimit = 10,
  ctx?: ActionContext
): Promise<Kapitel[]> {
  try {
    const { user, db } = await getContext(ctx);
    if (!user) throw new Error('Not authenticated');

    const snapshot = await getDocs(
      query(
        kapitelsCol(db, user.uid),
        where('projektId', '==', projektId),
        where('archived', '==', false),
        orderBy('order', 'asc')
      )
    );

    const kapitels: Kapitel[] = [];

    for (const docSnap of snapshot.docs) {
      const data = docSnap.data() as DocumentData;
      const kapitel: Kapitel = {
        id: docSnap.id,
        title: String(data.title ?? ''),
        projektId: String(data.projektId ?? 'default'),
        nummer: String(data.nummer ?? '1'),
        createdAt: toIso(data.createdAt),
        updatedAt: data.updatedAt ? toIso(data.updatedAt) : undefined,
        archived: Boolean(data.archived),
        archivedAt: data.archivedAt ? toIso(data.archivedAt) : undefined,
        quelleIds: Array.isArray(data.quelleIds) ? data.quelleIds : [],
        parentId: data.parentId ?? null,
        order: Number(data.order ?? 0),
        latestRun: data.latestRun
          ? {
              runId: String(data.latestRun.runId ?? ''),
              index: Number(data.latestRun.index ?? 0),
              status: normalizeRunStatus(data.latestRun.status),
              updatedAt: toIso(data.latestRun.updatedAt),
            }
          : undefined,
      };

      if (withRuns) {
        kapitel.runs = await getKapitelRuns(docSnap.id, runLimit, { user, db });
      }

      kapitels.push(kapitel);
    }

    return kapitels;
  } catch (error: unknown) {
    console.error('Error getting user Kapitels:', error);
    return [];
  }
}

export async function getCombinedGroups(kapitelId: string, runId: string): Promise<IntermediateGroupResult[]> {
  const user = await requireAuth();
  if (!user) return [];

  try {
    const db = await getFirestoreForUser();
    const snap = await getDocs(combinedGroupsCol(db, user.uid, kapitelId, runId));
    const groups: IntermediateGroupResult[] = snap.docs.map((d) => {
      const g = d.data() as DocumentData;
      return {
        id: d.id,
        groupNumber: Number(g.groupNumber ?? 0),
        content: String(g.content ?? ''),
        sourceQuelleIds: Array.isArray(g.sourceQuelleIds) ? g.sourceQuelleIds : [],
        heading: String(g.heading ?? ''),
        topic: String(g.topic ?? ''),
        model: String(g.model ?? ''),
        usage: normalizeUsage(g.usage),
        costUsd: Number(g.costUsd ?? 0),
        createdAt: toIso(g.createdAt),
        updatedAt: g.updatedAt ? toIso(g.updatedAt) : undefined,
      };
    });
    groups.sort((a, b) => a.groupNumber - b.groupNumber);
    return groups;
  } catch (error: unknown) {
    console.error('Error getting combined groups:', error);
    return [];
  }
}

export async function hasCombinedGroups(kapitelId: string, runId: string): Promise<boolean> {
  const user = await requireAuth();
  if (!user) return false;

  try {
    const db = await getFirestoreForUser();
    const snap = await getDocs(query(combinedGroupsCol(db, user.uid, kapitelId, runId), limit(1)));
    return !snap.empty;
  } catch (error: unknown) {
    console.error('Error checking combined groups existence:', error);
    return false;
  }
}

export async function createShortenRun(
  kapitelId: string,
  runId: string,
  contextKapitelIds: string[]
) {
  const user = await requireAuth();
  let runModel: 'gpt-5-nano' | 'gpt-5-mini' | 'gpt-5.2' = 'gpt-5-nano';
  if (user) {
    const db = await getFirestoreForUser();
    const runSnap = await getDoc(doc(db, 'users', user.uid, 'kapitels', kapitelId, 'runs', runId));
    runModel = normalizeRunModel(runSnap.exists() ? (runSnap.data() as DocumentData).model : null);
  }

  return fetchFastApi('/api/shorten', {
    kapitel_id: kapitelId,
    run_id: runId,
    context_kapitel_ids: contextKapitelIds,
    model: runModel,
  });
}

export async function createLeseflussRun(
  kapitelId: string,
  runId: string,
  contextKapitelIds: string[],
  aufgabenstellung: string
) {
  const user = await requireAuth();
  let runModel: 'gpt-5-nano' | 'gpt-5-mini' | 'gpt-5.2' = 'gpt-5-nano';
  if (user) {
    const db = await getFirestoreForUser();
    const runSnap = await getDoc(doc(db, 'users', user.uid, 'kapitels', kapitelId, 'runs', runId));
    runModel = normalizeRunModel(runSnap.exists() ? (runSnap.data() as DocumentData).model : null);
  }

  return fetchFastApi('/api/lesefluss', {
    kapitel_id: kapitelId,
    run_id: runId,
    context_kapitel_ids: contextKapitelIds,
    aufgabenstellung,
    model: runModel,
  });
}

export async function initCombinedRefinement(kapitelId: string, runId: string) {
  return fetchFastApi('/api/refine/combined/init', { kapitel_id: kapitelId, run_id: runId });
}

export async function createCombinedRefinement(kapitelId: string, runId: string, parentVersionId: string, userMessage: string) {
  return fetchFastApi('/api/refine/combined', {
    kapitel_id: kapitelId,
    run_id: runId,
    parent_version_id: parentVersionId,
    user_message: userMessage,
  });
}

export async function initShortenedRefinement(kapitelId: string, runId: string) {
  return fetchFastApi('/api/refine/shortened/init', { kapitel_id: kapitelId, run_id: runId });
}

export async function createShortenedRefinement(kapitelId: string, runId: string, parentVersionId: string, userMessage: string) {
  return fetchFastApi('/api/refine/shortened', {
    kapitel_id: kapitelId,
    run_id: runId,
    parent_version_id: parentVersionId,
    user_message: userMessage,
  });
}

export async function initLeseflussRefinement(kapitelId: string, runId: string) {
  return fetchFastApi('/api/refine/lesefluss/init', { kapitel_id: kapitelId, run_id: runId });
}

export async function createLeseflussRefinement(kapitelId: string, runId: string, parentVersionId: string, userMessage: string) {
  return fetchFastApi('/api/refine/lesefluss', {
    kapitel_id: kapitelId,
    run_id: runId,
    parent_version_id: parentVersionId,
    user_message: userMessage,
  });
}

export async function initResultRefinement(kapitelId: string, runId: string, quelleId: string) {
  return fetchFastApi('/api/refine/result/init', { kapitel_id: kapitelId, run_id: runId, quelle_id: quelleId });
}

export async function createResultRefinement(
  kapitelId: string,
  runId: string,
  quelleId: string,
  parentVersionId: string,
  userMessage: string
) {
  return fetchFastApi('/api/refine/result', {
    kapitel_id: kapitelId,
    run_id: runId,
    quelle_id: quelleId,
    parent_version_id: parentVersionId,
    user_message: userMessage,
  });
}

export async function getShortenedResult(kapitelId: string, runId: string): Promise<ShortenedResult | null> {
  const user = await requireAuth();
  if (!user) return null;
  try {
    const db = await getFirestoreForUser();
    const snap = await getDoc(doc(db, 'users', user.uid, 'kapitels', kapitelId, 'runs', runId, 'artifacts', 'shortened'));
    if (!snap.exists()) return null;
    const s = snap.data() as DocumentData;
    return {
      id: 'shortened',
      content: String(s.content ?? ''),
      originalLength: Number(s.originalLength ?? 0),
      shortenedLength: Number(s.shortenedLength ?? 0),
      usedKapitelIds: Array.isArray(s.usedKapitelIds) ? s.usedKapitelIds : [],
      model: String(s.model ?? ''),
      usage: normalizeUsage(s.usage),
      costUsd: Number(s.costUsd ?? 0),
      createdAt: toIso(s.createdAt),
      updatedAt: s.updatedAt ? toIso(s.updatedAt) : undefined,
      refinement: normalizeRefinement(s.refinement),
    };
  } catch (error: unknown) {
    console.error('Error getting shortened result:', error);
    return null;
  }
}

export async function getSummaries(kapitelId: string, runId: string): Promise<SummaryResult[]> {
  const user = await requireAuth();
  if (!user) return [];
  try {
    const db = await getFirestoreForUser();
    const snap = await getDocs(summariesCol(db, user.uid, kapitelId, runId));
    return snap.docs.map((d) => {
      const s = d.data() as DocumentData;
      return {
        id: d.id,
        content: String(s.content ?? ''),
        sourceKapitelId: String(s.sourceKapitelId ?? ''),
        sourceRunId: String(s.sourceRunId ?? ''),
        sourceType: normalizeSummarySourceType(s.sourceType),
        originalLength: Number(s.originalLength ?? 0),
        summaryLength: Number(s.summaryLength ?? 0),
        model: String(s.model ?? ''),
        costUsd: Number(s.costUsd ?? 0),
        usage: {
          inputTokens: Number((s.usage as Record<string, unknown> | undefined)?.inputTokens ?? 0),
          outputTokens: Number((s.usage as Record<string, unknown> | undefined)?.outputTokens ?? 0),
          totalTokens: Number((s.usage as Record<string, unknown> | undefined)?.totalTokens ?? 0),
        },
        createdAt: toIso(s.createdAt),
      };
    });
  } catch (error: unknown) {
    console.error('Error getting summaries:', error);
    return [];
  }
}

export async function getKapitelsWithCombinedText(
  kapitelIds: string[],
  runScanLimit = 20
): Promise<Record<string, boolean>> {
  const user = await requireAuth();
  if (!user) return {};

  const uniqueIds = Array.from(new Set(kapitelIds.filter(Boolean)));
  if (uniqueIds.length === 0) return {};

  try {
    const db = await getFirestoreForUser();

    const entries = await Promise.all(
      uniqueIds.map(async (kapitelId) => {
        try {
          const runsSnapshot = await getDocs(
            query(runsCol(db, user.uid, kapitelId), where('archived', '==', false), orderBy('index', 'desc'), limit(runScanLimit))
          );

          for (const runSnap of runsSnapshot.docs) {
            const runData = runSnap.data() as DocumentData;
            const combinedStatus = (runData.artifactsStatus as { combined?: unknown } | undefined)?.combined;
            if (combinedStatus === 'success') {
              return [kapitelId, true] as const;
            }

            const combinedSnap = await getDoc(artifactDoc(db, user.uid, kapitelId, runSnap.id, 'combined'));
            if (combinedSnap.exists()) {
              const combined = combinedSnap.data() as DocumentData;
              const content = typeof combined.content === 'string' ? combined.content : String(combined.content ?? '');
              if (content.trim().length > 0) return [kapitelId, true] as const;
            }
          }
        } catch (e) {
          console.error(`Error checking combined text for kapitel ${kapitelId}:`, e);
        }

        return [kapitelId, false] as const;
      })
    );

    return Object.fromEntries(entries);
  } catch (error) {
    console.error('Error checking combined text availability:', error);
    return Object.fromEntries(uniqueIds.map((id) => [id, false] as const));
  }
}

export async function getKapitelsWithShortenedText(
  kapitelIds: string[],
  runScanLimit = 20
): Promise<Record<string, boolean>> {
  const user = await requireAuth();
  if (!user) return {};

  const uniqueIds = Array.from(new Set(kapitelIds.filter(Boolean)));
  if (uniqueIds.length === 0) return {};

  try {
    const db = await getFirestoreForUser();

    const entries = await Promise.all(
      uniqueIds.map(async (kapitelId) => {
        try {
          const runsSnapshot = await getDocs(
            query(
              runsCol(db, user.uid, kapitelId),
              where('archived', '==', false),
              orderBy('index', 'desc'),
              limit(runScanLimit)
            )
          );

          for (const runSnap of runsSnapshot.docs) {
            const runData = runSnap.data() as DocumentData;
            const shortenedStatus = (runData.artifactsStatus as { shortened?: unknown } | undefined)?.shortened;
            if (shortenedStatus === 'success') {
              return [kapitelId, true] as const;
            }

            const shortenedSnap = await getDoc(artifactDoc(db, user.uid, kapitelId, runSnap.id, 'shortened'));
            if (shortenedSnap.exists()) {
              const shortened = shortenedSnap.data() as DocumentData;
              const content = typeof shortened.content === 'string' ? shortened.content : String(shortened.content ?? '');
              if (content.trim().length > 0) return [kapitelId, true] as const;
            }
          }
        } catch (e) {
          console.error(`Error checking shortened text for kapitel ${kapitelId}:`, e);
        }

        return [kapitelId, false] as const;
      })
    );

    return Object.fromEntries(entries);
  } catch (error) {
    console.error('Error checking shortened text availability:', error);
    return Object.fromEntries(uniqueIds.map((id) => [id, false] as const));
  }
}
