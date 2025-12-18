'use server';

import { getFirestoreForUser } from '@/app/lib/firebase/serverApp';
import {
  collection,
  addDoc,
  updateDoc,
  deleteDoc,
  doc,
  getDoc,
  getDocs,
  query,
  orderBy,
  limit,
  where,
  serverTimestamp,
  type Firestore,
  type DocumentReference,
} from 'firebase/firestore';
import { requireAuth, type AuthUser } from '@/app/lib/auth/server-auth';
import { revalidatePath } from 'next/cache';
import { cookies } from 'next/headers';

export type KapitelRunResult = {
  quelleId: string;
  resultContent: string;
  hasContent?: boolean;
  modelUsed: string;
  tokensUsed: number;
  inputTokens: number;
  cachedInputTokens: number;
  outputTokens: number;
  reasoningTokens: number;
  cost: number;
  createdAt: string;
};

export type CombinedResult = {
  id: string;
  combinedContent: string;
  sourceQuelleIds: string[];
  heading: string;
  topic: string;
  modelUsed: string;
  tokensUsed: number;
  inputTokens: number;
  cachedInputTokens: number;
  outputTokens: number;
  reasoningTokens: number;
  cost: number;
  createdAt: string;
};

export type IntermediateGroupResult = {
  id: string;
  groupNumber: number;
  combinedContent: string;
  sourceQuelleIds: string[];
  heading: string;
  topic: string;
  modelUsed: string;
  tokensUsed: number;
  inputTokens: number;
  cachedInputTokens: number;
  outputTokens: number;
  reasoningTokens: number;
  cost: number;
  createdAt: string;
};

export type ShortenedResult = {
  id: string;
  shortenedContent: string;
  explanation?: {
    lengthDecision: string;
    omittedTopics: string[];
    preservedFocus: string[];
    compressionNotes: string;
  };
  originalLength: number;
  shortenedLength: number;
  usedKapitelIds: string[];
  model: string;
  cost: number;
  tokensUsed: {
    input: number;
    cachedInput: number;
    output: number;
  };
  createdAt: string;
};

export type SummaryResult = {
  id: string;
  summaryContent: string;
  sourceKapitelId: string;
  sourceRunId: string;
  sourceType: 'combined' | 'shortened';
  originalLength: number;
  summaryLength: number;
  model: string;
  cost: number;
  tokensUsed: {
    input: number;
    output: number;
  };
  createdAt: string;
};

export type LeseflussResult = {
  id: string;
  leseflussContent: string;
  aufgabenstellung: string;
  explanation: string;
  originalLength: number;
  leseflussLength: number;
  usedKapitelIds: string[];
  model: string;
  cost: number;
  tokensUsed: {
    input: number;
    cachedInput: number;
    output: number;
  };
  createdAt: string;
};

export type KapitelRun = {
  id: string;
  index: number;
  instruction: string;
  model: string;
  createdAt: string;
  results: KapitelRunResult[];
  combined?: CombinedResult | null;
  intermediateGroups?: IntermediateGroupResult[];
  shortened?: ShortenedResult | null;
  lesefluss?: LeseflussResult | null;
  summaries?: SummaryResult[];
  promptTemplateId?: string;
  promptPayload?: Record<string, any>;
  autoCombine?: boolean;
  ueberschrift?: string;
  thema?: string;
  grundlegendeInformationen?: string | null;
};

export type Kapitel = {
  id: string;
  title: string;
  projektId: string;
  nummer?: string; // e.g., "1", "1.1", "1.1.1" - hierarchical chapter number
  createdAt: string;
  quelleIds: string[];
  runs?: KapitelRun[];
  parentId?: string | null;
  order?: number;
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

// Helper function to check for circular references in parent chain
async function checkCircularReference(
  db: Firestore,
  userId: string,
  kapitelId: string,
  targetParentId: string | null
): Promise<boolean> {
  if (!targetParentId) return false;

  let currentId: string | null = targetParentId;
  const visited = new Set<string>([kapitelId]);

  while (currentId) {
    if (visited.has(currentId)) {
      return true; // Circular reference detected
    }
    visited.add(currentId);

    const parentRef: DocumentReference = doc(db, 'users', userId, 'kapitels', currentId);
    const parentDoc = await getDoc(parentRef);

    if (!parentDoc.exists()) {
      break;
    }

    currentId = parentDoc.data()?.parentId || null;
  }

  return false;
}

// Helper function to calculate depth of a Kapitel in the hierarchy
async function getKapitelDepth(
  db: Firestore,
  userId: string,
  kapitelId: string | null
): Promise<number> {
  if (!kapitelId) return 0;

  let depth = 0;
  let currentId: string | null = kapitelId;

  while (currentId && depth < 10) { // Safety limit
    const kapitelRef: DocumentReference = doc(db, 'users', userId, 'kapitels', currentId);
    const kapitelDoc = await getDoc(kapitelRef);

    if (!kapitelDoc.exists()) {
      break;
    }

    currentId = kapitelDoc.data()?.parentId || null;
    if (currentId) depth++;
  }

  return depth;
}

// Helper function to get next order value for siblings
async function getNextOrderForParent(
  db: Firestore,
  userId: string,
  parentId: string | null
): Promise<number> {
  const kapitelsRef = collection(db, 'users', userId, 'kapitels');
  let q;

  if (parentId === null) {
    // Root level kapitels (no parent)
    q = query(kapitelsRef, orderBy('order', 'desc'), limit(1));
  } else {
    // Child kapitels with specific parent
    q = query(kapitelsRef, orderBy('order', 'desc'), limit(1));
  }

  const snapshot = await getDocs(q);

  if (snapshot.empty) {
    return 0;
  }

  // Filter by parentId in memory (Firestore doesn't support complex queries on optional fields)
  const siblings = snapshot.docs.filter(doc => {
    const data = doc.data();
    return (data.parentId || null) === parentId;
  });

  if (siblings.length === 0) {
    return 0;
  }

  const maxOrder = Math.max(...siblings.map(doc => doc.data().order || 0));
  return maxOrder + 1;
}

export async function createKapitel(
  title: string,
  quelleIds: string[],
  parentId: string | null,
  nummer: string,
  projektId: string
) {
  try {
    const user = await requireAuth();
    if (!user) {
      return { success: false, error: 'Not authenticated' };
    }
    const db = await getFirestoreForUser();

    // Validate parentId if provided
    if (parentId) {
      const parentRef = doc(db, 'users', user.uid, 'kapitels', parentId);
      const parentDoc = await getDoc(parentRef);

      if (!parentDoc.exists()) {
        return { success: false, error: 'Parent Kapitel not found' };
      }

      // Check depth - enforce maximum of 5 levels
      const parentDepth = await getKapitelDepth(db, user.uid, parentId);
      if (parentDepth >= 4) {
        return {
          success: false,
          error: 'Maximum nesting depth (5 levels) would be exceeded',
        };
      }
    }

    // Get next order value for siblings
    const order = await getNextOrderForParent(db, user.uid, parentId || null);

    const kapitelsRef = collection(db, 'users', user.uid, 'kapitels');
    const docRef = await addDoc(kapitelsRef, {
      title,
      projektId,
      nummer: nummer || '1', // Default to '1' if not provided
      quelleIds,
      parentId: parentId || null,
      order,
      createdAt: serverTimestamp(),
    });

    revalidatePath('/dashboard');
    return { success: true, id: docRef.id };
  } catch (error: any) {
    console.error('Error creating Kapitel:', error);
    return { success: false, error: error.message };
  }
}

export async function updateKapitelQuellen(kapitelId: string, quelleIds: string[]) {
  try {
    const user = await requireAuth();
    if (!user) {
      return { success: false, error: 'Not authenticated' };
    }
    const db = await getFirestoreForUser();

    const kapitelRef = doc(db, 'users', user.uid, 'kapitels', kapitelId);
    const kapitelDoc = await getDoc(kapitelRef);
    if (!kapitelDoc.exists()) {
      throw new Error('Kapitel not found');
    }

    await updateDoc(kapitelRef, {
      quelleIds,
      updatedAt: serverTimestamp(),
    });

    revalidatePath('/dashboard');
    return { success: true };
  } catch (error: any) {
    console.error('Error updating Kapitel Quellen:', error);
    return { success: false, error: error.message };
  }
}

export async function updateKapitelParent(
  kapitelId: string,
  newParentId: string | null
) {
  try {
    const user = await requireAuth();
    if (!user) {
      return { success: false, error: 'Not authenticated' };
    }
    const db = await getFirestoreForUser();

    const kapitelRef = doc(db, 'users', user.uid, 'kapitels', kapitelId);
    const kapitelDoc = await getDoc(kapitelRef);
    if (!kapitelDoc.exists()) {
      return { success: false, error: 'Kapitel not found' };
    }

    // Check for circular reference
    if (newParentId) {
      const hasCircular = await checkCircularReference(
        db,
        user.uid,
        kapitelId,
        newParentId
      );

      if (hasCircular) {
        return {
          success: false,
          error: 'Cannot set parent: would create circular reference',
        };
      }

      // Validate new parent exists
      const parentRef = doc(db, 'users', user.uid, 'kapitels', newParentId);
      const parentDoc = await getDoc(parentRef);
      if (!parentDoc.exists()) {
        return { success: false, error: 'Parent Kapitel not found' };
      }

      // Check depth
      const parentDepth = await getKapitelDepth(db, user.uid, newParentId);
      if (parentDepth >= 4) {
        return {
          success: false,
          error: 'Maximum nesting depth (5 levels) would be exceeded',
        };
      }
    }

    // Get next order for new parent's children
    const order = await getNextOrderForParent(db, user.uid, newParentId);

    await updateDoc(kapitelRef, {
      parentId: newParentId,
      order,
      updatedAt: serverTimestamp(),
    });

    revalidatePath('/dashboard');
    return { success: true };
  } catch (error: any) {
    console.error('Error updating Kapitel parent:', error);
    return { success: false, error: error.message };
  }
}

export async function updateKapitelTitle(
  kapitelId: string,
  title: string,
  nummer: string
) {
  try {
    const user = await requireAuth();
    if (!user) {
      return { success: false, error: 'Not authenticated' };
    }
    const db = await getFirestoreForUser();

    const kapitelRef = doc(db, 'users', user.uid, 'kapitels', kapitelId);
    const kapitelDoc = await getDoc(kapitelRef);
    if (!kapitelDoc.exists()) {
      throw new Error('Kapitel not found');
    }

    await updateDoc(kapitelRef, {
      title,
      nummer,
      updatedAt: serverTimestamp(),
    });

    revalidatePath('/dashboard');
    return { success: true };
  } catch (error: any) {
    console.error('Error updating Kapitel title:', error);
    return { success: false, error: error.message };
  }
}

export async function deleteKapitel(
  kapitelId: string,
  deleteStrategy: 'promote' | 'cascade' = 'promote'
) {
  try {
    const user = await requireAuth();
    if (!user) {
      return { success: false, error: 'Not authenticated' };
    }
    const db = await getFirestoreForUser();

    const kapitelRef = doc(db, 'users', user.uid, 'kapitels', kapitelId);
    const kapitelDoc = await getDoc(kapitelRef);
    if (!kapitelDoc.exists()) {
      throw new Error('Kapitel not found');
    }

    const kapitelData = kapitelDoc.data();
    const parentId = kapitelData.parentId || null;

    // Find all children of this Kapitel
    const kapitelsRef = collection(db, 'users', user.uid, 'kapitels');
    const childrenSnapshot = await getDocs(kapitelsRef);
    const children = childrenSnapshot.docs
      .filter((doc) => doc.data().parentId === kapitelId)
      .map((doc) => ({ id: doc.id, ...doc.data() }));

    if (deleteStrategy === 'cascade') {
      // Recursively delete all descendants
      for (const child of children) {
        await deleteKapitel(child.id, 'cascade');
      }
    } else {
      // Promote children to parent's level
      for (const child of children) {
        const childRef = doc(db, 'users', user.uid, 'kapitels', child.id);
        await updateDoc(childRef, {
          parentId: parentId,
          updatedAt: serverTimestamp(),
        });
      }
    }

    // Delete the Kapitel itself
    await deleteDoc(kapitelRef);
    revalidatePath('/dashboard');
    return { success: true };
  } catch (error: any) {
    console.error('Error deleting Kapitel:', error);
    return { success: false, error: error.message };
  }
}

export async function createKapitelRun(
  kapitelId: string,
  instruction: string,
  model: string,
  options?: {
    promptTemplateId?: string;
    promptPayload?: Record<string, any>;
    autoCombine?: boolean;
    grundlegendeInformationen?: string;
    ueberschrift?: string; // Heading for the chapter
    thema?: string; // Topic/theme (can be same as instruction or separate)
  }
) {
  try {
    const user = await requireAuth();
    if (!user) {
      return { success: false, error: 'Not authenticated' };
    }
    const db = await getFirestoreForUser();

    const kapitelRef = doc(db, 'users', user.uid, 'kapitels', kapitelId);
    const kapitelDoc = await getDoc(kapitelRef);
    if (!kapitelDoc.exists()) {
      return { success: false, error: 'Kapitel not found' };
    }
    const projektId = kapitelDoc.data()?.projektId || 'default';

    const runsRef = collection(db, 'users', user.uid, 'kapitels', kapitelId, 'runs');

    // Determine next run index
    const lastRunSnapshot = await getDocs(query(runsRef, orderBy('index', 'desc'), limit(1)));
    const lastIndex = lastRunSnapshot.empty ? 0 : (lastRunSnapshot.docs[0].data().index || 0);
    const nextIndex = lastIndex + 1;

    const runDoc = await addDoc(runsRef, {
      instruction,
      model,
      projektId,
      index: nextIndex,
      createdAt: serverTimestamp(),
      promptTemplateId: options?.promptTemplateId,
      promptPayload: options?.promptPayload,
      autoCombine: options?.autoCombine ?? false,
      grundlegendeInformationen: options?.grundlegendeInformationen || null,
      ueberschrift: options?.ueberschrift || null,
      thema: options?.thema || null,
    });

    revalidatePath('/dashboard');
    return { success: true, runId: runDoc.id, index: nextIndex };
  } catch (error: any) {
    console.error('Error creating Kapitel run:', error);
    return { success: false, error: error.message };
  }
}

export async function getKapitelRuns(
  kapitelId: string,
  runLimit = 10,
  ctx?: ActionContext
): Promise<KapitelRun[]> {
  try {
    const { user, db } = await getContext(ctx);
    if (!user) {
      throw new Error('Not authenticated');
    }

    const runsRef = collection(db, 'users', user.uid, 'kapitels', kapitelId, 'runs');
    const runsSnapshot = await getDocs(query(runsRef, orderBy('index', 'desc'), limit(runLimit)));

    // Parallelize fetching all runs and their subcollections
    const runs: KapitelRun[] = await Promise.all(
      runsSnapshot.docs.map(async (runDoc) => {
        const runData = runDoc.data();

        // Define all collection references
        const combinedRef = collection(
          db,
          'users',
          user.uid,
          'kapitels',
          kapitelId,
          'runs',
          runDoc.id,
          'combined'
        );
        const shortenedRef = collection(
          db,
          'users',
          user.uid,
          'kapitels',
          kapitelId,
          'runs',
          runDoc.id,
          'shortened'
        );
        const leseflussRef = collection(
          db,
          'users',
          user.uid,
          'kapitels',
          kapitelId,
          'runs',
          runDoc.id,
          'lesefluss'
        );
        const intermediateGroupsRef = collection(
          db,
          'users',
          user.uid,
          'kapitels',
          kapitelId,
          'runs',
          runDoc.id,
          'intermediate_groups'
        );
        const resultsRef = collection(
          db,
          'users',
          user.uid,
          'kapitels',
          kapitelId,
          'runs',
          runDoc.id,
          'results'
        );

        // Fetch all subcollections in parallel
        const [
          combinedSnapshot,
          shortenedSnapshot,
          leseflussSnapshot,
          intermediateGroupsSnapshot,
          resultsSnapshot,
        ] = await Promise.all([
          getDocs(combinedRef),
          getDocs(shortenedRef),
          getDocs(leseflussRef),
          getDocs(intermediateGroupsRef),
          getDocs(resultsRef),
        ]);

        // Transform combined result
        let combined: CombinedResult | null = null;
        if (!combinedSnapshot.empty) {
          const doc = combinedSnapshot.docs[0];
          const c = doc.data();
          combined = {
            id: doc.id,
            combinedContent: c.combined_content ?? c.combinedContent ?? '',
            sourceQuelleIds: c.source_quelle_ids ?? c.sourceQuelleIds ?? [],
            heading: c.heading ?? '',
            topic: c.topic ?? '',
            modelUsed: c.model_used ?? c.modelUsed ?? '',
            tokensUsed: c.tokens_used ?? c.tokensUsed ?? 0,
            inputTokens: c.input_tokens ?? c.inputTokens ?? 0,
            cachedInputTokens: c.cached_input_tokens ?? c.cachedInputTokens ?? 0,
            outputTokens: c.output_tokens ?? c.outputTokens ?? 0,
            reasoningTokens: c.reasoning_tokens ?? c.reasoningTokens ?? 0,
            cost: c.cost ?? 0,
            createdAt:
              c.created_at?.toDate?.()?.toISOString() ||
              c.createdAt?.toDate?.()?.toISOString() ||
              new Date().toISOString(),
          };
        }

        // Transform shortened result
        let shortened: ShortenedResult | null = null;
        if (!shortenedSnapshot.empty) {
          const doc = shortenedSnapshot.docs[0];
          const s = doc.data();
          shortened = {
            id: doc.id,
            shortenedContent: s.shortened_content ?? s.shortenedContent ?? '',
            explanation: s.explanation
              ? {
                  lengthDecision: s.explanation.length_decision ?? '',
                  omittedTopics: s.explanation.omitted_topics ?? [],
                  preservedFocus: s.explanation.preserved_focus ?? [],
                  compressionNotes: s.explanation.compression_notes ?? '',
                }
              : undefined,
            originalLength: s.original_length ?? s.originalLength ?? 0,
            shortenedLength: s.shortened_length ?? s.shortenedLength ?? 0,
            usedKapitelIds: s.used_kapitel_ids ?? s.usedKapitelIds ?? [],
            model: s.model ?? '',
            cost: s.cost ?? 0,
            tokensUsed: s.tokens_used ?? s.tokensUsed ?? { input: 0, cachedInput: 0, output: 0 },
            createdAt:
              s.created_at?.toDate?.()?.toISOString() ||
              s.createdAt?.toDate?.()?.toISOString() ||
              new Date().toISOString(),
          };
        }

        // Transform lesefluss result
        let lesefluss: LeseflussResult | null = null;
        if (!leseflussSnapshot.empty) {
          const doc = leseflussSnapshot.docs[0];
          const l = doc.data();
          lesefluss = {
            id: doc.id,
            leseflussContent: l.lesefluss_content ?? l.leseflussContent ?? '',
            aufgabenstellung: l.aufgabenstellung ?? '',
            explanation: l.explanation ?? '',
            originalLength: l.original_length ?? l.originalLength ?? 0,
            leseflussLength: l.lesefluss_length ?? l.leseflussLength ?? 0,
            usedKapitelIds: l.used_kapitel_ids ?? l.usedKapitelIds ?? [],
            model: l.model ?? '',
            cost: l.cost ?? 0,
            tokensUsed: l.tokens_used ?? l.tokensUsed ?? { input: 0, cachedInput: 0, output: 0 },
            createdAt:
              l.created_at?.toDate?.()?.toISOString() ||
              l.createdAt?.toDate?.()?.toISOString() ||
              new Date().toISOString(),
          };
        }

        // Transform intermediate groups
        const intermediateGroups: IntermediateGroupResult[] = [];
        if (!intermediateGroupsSnapshot.empty) {
          for (const groupDoc of intermediateGroupsSnapshot.docs) {
            const g = groupDoc.data();
            intermediateGroups.push({
              id: groupDoc.id,
              groupNumber: g.group_number ?? 0,
              combinedContent: g.combined_content ?? g.combinedContent ?? '',
              sourceQuelleIds: g.source_quelle_ids ?? g.sourceQuelleIds ?? [],
              heading: g.heading ?? '',
              topic: g.topic ?? '',
              modelUsed: g.model_used ?? g.modelUsed ?? '',
              tokensUsed: g.tokens_used ?? g.tokensUsed ?? 0,
              inputTokens: g.input_tokens ?? g.inputTokens ?? 0,
              cachedInputTokens: g.cached_input_tokens ?? g.cachedInputTokens ?? 0,
              outputTokens: g.output_tokens ?? g.outputTokens ?? 0,
              reasoningTokens: g.reasoning_tokens ?? g.reasoningTokens ?? 0,
              cost: g.cost ?? 0,
              createdAt:
                g.created_at?.toDate?.()?.toISOString() ||
                g.createdAt?.toDate?.()?.toISOString() ||
                new Date().toISOString(),
            });
          }
          // Sort by group number
          intermediateGroups.sort((a, b) => a.groupNumber - b.groupNumber);
        }

        // Transform results
        const results: KapitelRunResult[] = resultsSnapshot.docs.map((resDoc) => {
          const resData = resDoc.data();
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

        // Return the complete run object
        return {
          id: runDoc.id,
          index: runData.index || 0,
          instruction: runData.instruction || '',
          model: runData.model || '',
          ueberschrift: runData.ueberschrift || runData.heading || '',
          thema: runData.thema || runData.instruction || '',
          grundlegendeInformationen: runData.grundlegendeInformationen || null,
          promptTemplateId: runData.promptTemplateId,
          promptPayload: runData.promptPayload,
          autoCombine: runData.autoCombine ?? false,
          createdAt:
            runData.createdAt?.toDate?.()?.toISOString() ||
            runData.created_at?.toDate?.()?.toISOString() ||
            new Date().toISOString(),
          results,
          combined,
          intermediateGroups: intermediateGroups.length > 0 ? intermediateGroups : undefined,
          shortened: shortened ?? undefined,
          lesefluss: lesefluss ?? undefined,
        };
      })
    );

    return runs;
  } catch (error: any) {
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
    if (!user) {
      throw new Error('Not authenticated');
    }

    const kapitelsRef = collection(db, 'users', user.uid, 'kapitels');
    const snapshot = await getDocs(
      query(kapitelsRef, where('projektId', '==', projektId), orderBy('createdAt', 'desc'))
    );

    const kapitels: Kapitel[] = [];

    for (const kapitelDoc of snapshot.docs) {
      const data = kapitelDoc.data();
      const kapitel: Kapitel = {
        id: kapitelDoc.id,
        title: data.title,
        projektId: data.projektId || 'default',
        nummer: data.nummer || '1', // Default to '1' for existing kapitels without nummer
        quelleIds: data.quelleIds || [],
        createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
        parentId: data.parentId || null,
        order: data.order ?? 0,
      };

      if (withRuns) {
        kapitel.runs = await getKapitelRuns(kapitelDoc.id, runLimit, { user, db });
      }

      kapitels.push(kapitel);
    }

    return kapitels;
  } catch (error: any) {
    console.error('Error getting user Kapitels:', error);
    return [];
  }
}

/**
 * Create a shortening run for a Kapitel
 */
export async function createShortenRun(
  kapitelId: string,
  runId: string,
  contextKapitelIds: string[],
  model: 'gpt-5-nano' | 'gpt-5-mini' | 'gpt-5.2' = 'gpt-5-nano'
) {
  const user = await requireAuth();
  if (!user) {
    return { success: false, error: 'Not authenticated' };
  }

  try {
    const apiBaseUrl = process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://localhost:8000';

    // Get the auth token from session cookie
    const cookieStore = await cookies();
    const authToken = cookieStore.get('__session')?.value;

    if (!authToken) {
      return { success: false, error: 'Deine Sitzung ist abgelaufen. Bitte melde dich erneut an.' };
    }

    // Call the FastAPI endpoint
    let response: Response;
    try {
      response = await fetch(`${apiBaseUrl}/api/shorten`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({
          kapitel_id: kapitelId,
          run_id: runId,
          context_kapitel_ids: contextKapitelIds,
          model: model,
        }),
      });
    } catch (err) {
      return {
        success: false,
        error: 'FastAPI-Server ist nicht erreichbar. Das ist ein Server-Problem – bitte später erneut versuchen.',
      };
    }

    if (response.status === 401) {
      return { success: false, error: 'Deine Sitzung ist abgelaufen. Bitte melde dich erneut an.' };
    }

    if (response.status >= 500) {
      return {
        success: false,
        error: 'FastAPI-Server antwortet gerade nicht. Das liegt nicht an dir – versuche es später erneut.',
      };
    }

    if (!response.ok) {
      const errorText = await response.text();
      return { success: false, error: errorText || 'Kürzen konnte nicht gestartet werden.' };
    }

    const result = await response.json();
    console.log('Shortening queued:', result);

    // Revalidate the dashboard path
    revalidatePath('/dashboard');

    return { success: true, data: result };
  } catch (error: any) {
    console.error('Error creating shorten run:', error);
    return { success: false, error: error?.message || 'Failed to create shorten run' };
  }
}

export async function createLeseflussRun(
  kapitelId: string,
  runId: string,
  contextKapitelIds: string[],
  aufgabenstellung: string,
  model: 'gpt-5-nano' | 'gpt-5-mini' | 'gpt-5.2' = 'gpt-5-nano'
) {
  const user = await requireAuth();
  if (!user) {
    return { success: false, error: 'Not authenticated' };
  }

  try {
    const apiBaseUrl = process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://localhost:8000';

    const cookieStore = await cookies();
    const authToken = cookieStore.get('__session')?.value;

    if (!authToken) {
      return { success: false, error: 'Deine Sitzung ist abgelaufen. Bitte melde dich erneut an.' };
    }

    let response: Response;
    try {
      response = await fetch(`${apiBaseUrl}/api/lesefluss`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({
          kapitel_id: kapitelId,
          run_id: runId,
          context_kapitel_ids: contextKapitelIds,
          aufgabenstellung: aufgabenstellung,
          model: model,
        }),
      });
    } catch (err) {
      return {
        success: false,
        error: 'FastAPI-Server ist nicht erreichbar. Das ist ein Server-Problem – bitte später erneut versuchen.',
      };
    }

    if (response.status === 401) {
      return { success: false, error: 'Deine Sitzung ist abgelaufen. Bitte melde dich erneut an.' };
    }

    if (response.status >= 500) {
      return {
        success: false,
        error: 'FastAPI-Server antwortet gerade nicht. Das liegt nicht an dir – versuche es später erneut.',
      };
    }

    if (!response.ok) {
      const errorText = await response.text();
      return { success: false, error: errorText || 'Lese Fluss verbessern konnte nicht gestartet werden.' };
    }

    const result = await response.json();
    console.log('Lesefluss queued:', result);

    revalidatePath('/dashboard');

    return { success: true, data: result };
  } catch (error: any) {
    console.error('Error creating lesefluss run:', error);
    return { success: false, error: error?.message || 'Failed to create lesefluss run' };
  }
}

/**
 * Get the shortened result for a specific run
 */
export async function getShortenedResult(
  kapitelId: string,
  runId: string
): Promise<ShortenedResult | null> {
  const user = await requireAuth();
  if (!user) {
    return null;
  }

  try {
    const db = await getFirestoreForUser();

    const shortenedRef = doc(
      db,
      'users',
      user.uid,
      'kapitels',
      kapitelId,
      'runs',
      runId,
      'shortened',
      'shortened'
    );

    const shortenedDoc = await getDoc(shortenedRef);

    if (!shortenedDoc.exists()) {
      return null;
    }

    const data = shortenedDoc.data();

    return {
      id: shortenedDoc.id,
      shortenedContent: data.shortened_content || '',
      originalLength: data.original_length || 0,
      shortenedLength: data.shortened_length || 0,
      usedKapitelIds: data.used_kapitel_ids || [],
      model: data.model || '',
      cost: data.cost || 0,
      tokensUsed: data.tokens_used || { input: 0, cachedInput: 0, output: 0 },
      createdAt: data.created_at || new Date().toISOString(),
    };
  } catch (error: any) {
    console.error('Error getting shortened result:', error);
    return null;
  }
}

/**
 * Get all summaries for a run
 */
export async function getSummaries(
  kapitelId: string,
  runId: string
): Promise<SummaryResult[]> {
  const user = await requireAuth();
  if (!user) {
    return [];
  }

  try {
    const db = await getFirestoreForUser();

    const summariesRef = collection(
      db,
      'users',
      user.uid,
      'kapitels',
      kapitelId,
      'runs',
      runId,
      'summaries'
    );

    const snapshot = await getDocs(summariesRef);

    const summaries: SummaryResult[] = [];

    for (const summaryDoc of snapshot.docs) {
      const data = summaryDoc.data();
      summaries.push({
        id: summaryDoc.id,
        summaryContent: data.summary_content || '',
        sourceKapitelId: data.source_kapitel_id || '',
        sourceRunId: data.source_run_id || '',
        sourceType: data.source_type || 'combined',
        originalLength: data.original_length || 0,
        summaryLength: data.summary_length || 0,
        model: data.model || '',
        cost: data.cost || 0,
        tokensUsed: data.tokens_used || { input: 0, output: 0 },
        createdAt: data.created_at || new Date().toISOString(),
      });
    }

    return summaries;
  } catch (error: any) {
    console.error('Error getting summaries:', error);
    return [];
  }
}
