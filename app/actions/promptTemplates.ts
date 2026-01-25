'use server';

import { revalidatePath } from 'next/cache';
import { getFirestoreForUser } from '@/app/lib/firebase/serverApp';
import { requireAuth } from '@/app/lib/auth/server-auth';
import type {
  ActivePromptSelections,
  PromptStage,
  PromptTemplate,
  PromptTemplatePayload,
  SystemPromptPermissions,
  SystemPromptTemplateMeta,
} from '@/app/types/prompts';
import {
  DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY,
  LEGACY_SYSTEM_PROMPT_TEMPLATE_KEY,
  STAGE_CONFIG,
  MAX_TEMPLATES_PER_STAGE,
  MAX_NAME_LENGTH,
  MIN_NAME_LENGTH,
} from '@/app/lib/prompts/promptConfig';
import { cookies } from 'next/headers';
import {
  collection,
  query,
  where,
  getDocs,
  addDoc,
  updateDoc,
  deleteDoc,
  doc,
  serverTimestamp,
  getDoc,
  setDoc,
} from 'firebase/firestore';

const API_BASE_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://localhost:8000';

function validatePlaceholders(stage: PromptStage, instructions: string): string | null {
  const config = STAGE_CONFIG[stage];
  const missing = (config.requiredPlaceholders || []).filter((ph) => !instructions.includes(ph));
  if (missing.length > 0) {
    return `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`;
  }
  return null;
}

const SYSTEM_STAGES: PromptStage[] = ['process_quelle', 'combine', 'shorten', 'lesefluss', 'summary', 'gliederung'];
const PROMPT_DEFAULTS_VERSION = 2;

function fallbackSystemTemplates(): SystemPromptTemplateMeta[] {
  // Fail closed: if we can't reach the backend, don't guess which system templates exist
  // (archived templates must not become selectable due to a transient error).
  return [];
}

async function loadSystemTemplates(): Promise<{
  systemTemplates: SystemPromptTemplateMeta[];
  systemPermissions: SystemPromptPermissions;
  source: 'backend' | 'fallback';
}> {
  const store = await cookies();
  const token = store.get('__session')?.value;
  if (!token) {
    return {
      systemTemplates: fallbackSystemTemplates(),
      systemPermissions: { canDuplicateSystemPrompts: false },
      source: 'fallback',
    };
  }

  try {
    const res = await fetch(`<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      return {
        systemTemplates: fallbackSystemTemplates(),
        systemPermissions: { canDuplicateSystemPrompts: false },
        source: 'fallback',
      };
    }

    const raw = Array.isArray((data as any)?.templates) ? ((data as any).templates as any[]) : [];
    const templates: SystemPromptTemplateMeta[] = raw
      .map((t) => {
        const stage = t?.stage;
        const templateKey = t?.templateKey;
        const name = t?.name;
        if (!SYSTEM_STAGES.includes(stage)) return null;
        if (typeof templateKey !== 'string' || !templateKey.trim()) return null;
        return {
          stage,
          templateKey: templateKey.trim(),
          name: typeof name === 'string' && name.trim() ? name.trim() : templateKey.trim(),
          createdAt: typeof t?.createdAt === 'string' ? t.createdAt : null,
          updatedAt: typeof t?.updatedAt === 'string' ? t.updatedAt : null,
        } satisfies SystemPromptTemplateMeta;
      })
      .filter(Boolean) as SystemPromptTemplateMeta[];

    const perms = (data as any)?.permissions;
    const canDuplicate = perms?.canDuplicateSystemPrompts === true;

    return {
      systemTemplates: templates,
      systemPermissions: { canDuplicateSystemPrompts: canDuplicate },
      source: 'backend',
    };
  } catch {
    return {
      systemTemplates: fallbackSystemTemplates(),
      systemPermissions: { canDuplicateSystemPrompts: false },
      source: 'fallback',
    };
  }
}

function isoToMs(iso: string | null): number {
  if (!iso) return 0;
  // Be tolerant of buggy server timestamps like "...+00:00Z" from older deployments.
  const cleaned = iso.endsWith('Z') && iso.includes('+') ? iso.slice(0, -1) : iso;
  const t = Date.parse(cleaned);
  return Number.isFinite(t) ? t : 0;
}

function pickNewestSystemTemplateKeyForStage(
  stage: PromptStage,
  systemTemplates: SystemPromptTemplateMeta[]
): string | null {
  const list = systemTemplates.filter((t) => t.stage === stage);
  if (list.length === 0) return null;

  const rank = (key: string) => (key === 'default_v2' ? 0 : key === 'default' ? 1 : 2);

  list.sort((a, b) => {
    const ta = isoToMs(a.updatedAt || a.createdAt);
    const tb = isoToMs(b.updatedAt || b.createdAt);
    if (ta !== tb) return tb - ta;
    const ra = rank(a.templateKey);
    const rb = rank(b.templateKey);
    if (ra !== rb) return ra - rb;
    return a.name.localeCompare(b.name, 'de');
  });

  return list[0].templateKey;
}

async function ensureLimits(stage: PromptStage, userId: string, db: any) {
  const templatesRef = collection(db, 'users', userId, 'promptTemplates');
  const existing = await getDocs(query(templatesRef, where('stage', '==', stage)));
  if (existing.size >= MAX_TEMPLATES_PER_STAGE) {
    throw new Error(`<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`);
  }
}

export async function listPromptTemplates(): Promise<{
  templates: PromptTemplate[];
  active: ActivePromptSelections;
  askOnEachProcess: boolean;
  systemTemplates: SystemPromptTemplateMeta[];
  systemPermissions: SystemPromptPermissions;
}> {
  const user = await requireAuth();
  if (!user) {
    throw new Error('Not authenticated');
  }
  const db = await getFirestoreForUser();

  const templatesRef = collection(db, 'users', user.uid, 'promptTemplates');
  const snapshot = await getDocs(templatesRef);
  const templates: PromptTemplate[] = snapshot.docs.map((d) => {
    const data = d.data() as any;
    return {
      id: d.id,
      stage: data.stage,
      name: data.name,
      instructions: data.instructions,
      placeholders: data.placeholders || [],
      createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
      updatedAt: data.updatedAt?.toDate?.()?.toISOString() || new Date().toISOString(),
    };
  });

  const settingsDoc = await getDoc(doc(db, 'users', user.uid, 'promptSettings', 'active'));
  const activeDoc = (settingsDoc.exists() ? settingsDoc.data() : {}) as any;

  const { systemTemplates, systemPermissions, source } = await loadSystemTemplates();

  const userTemplateIdsByStage = new Map<PromptStage, Set<string>>();
  for (const stage of SYSTEM_STAGES) {
    userTemplateIdsByStage.set(
      stage,
      new Set(templates.filter((t) => t.stage === stage).map((t) => t.id))
    );
  }

  const systemKeysByStage = new Map<PromptStage, Set<string>>();
  for (const stage of SYSTEM_STAGES) {
    systemKeysByStage.set(
      stage,
      new Set(systemTemplates.filter((t) => t.stage === stage).map((t) => t.templateKey))
    );
  }

  const activeTemplates = (activeDoc.activeTemplates || {}) as ActivePromptSelections;
  let returnedActive: ActivePromptSelections = activeTemplates;
  let defaultsVersion = Number(activeDoc.promptDefaultsVersion || 0);

  if (source === 'backend') {
    const sanitizedActive: ActivePromptSelections = { ...activeTemplates };
    let changed = false;

    for (const stage of SYSTEM_STAGES) {
      const selected =
        (sanitizedActive[stage] as string | undefined) || DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY;
      const userIds = userTemplateIdsByStage.get(stage) || new Set<string>();
      const systemKeys = systemKeysByStage.get(stage) || new Set<string>();

      // One-time migration: move legacy v1 defaults ("default" or missing) to v2.
      if (defaultsVersion < PROMPT_DEFAULTS_VERSION) {
        if (!sanitizedActive[stage] || selected === LEGACY_SYSTEM_PROMPT_TEMPLATE_KEY) {
          sanitizedActive[stage] = DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY;
          changed = true;
        }
      }

      // Keep valid user templates.
      if (selected && selected !== LEGACY_SYSTEM_PROMPT_TEMPLATE_KEY && userIds.has(selected)) {
        continue;
      }

      // System selection (or unknown) must be currently selectable; otherwise fall back to newest.
      if (!systemKeys.has(selected)) {
        const fallbackKey =
          pickNewestSystemTemplateKeyForStage(stage, systemTemplates) ||
          DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY;
        if (fallbackKey !== selected) {
          sanitizedActive[stage] = fallbackKey;
          changed = true;
        }
      }
    }

    if (defaultsVersion < PROMPT_DEFAULTS_VERSION) {
      defaultsVersion = PROMPT_DEFAULTS_VERSION;
      changed = true;
    }

    if (changed) {
      const settingsRef = doc(db, 'users', user.uid, 'promptSettings', 'active');
      await setDoc(
        settingsRef,
        {
          activeTemplates: sanitizedActive,
          promptDefaultsVersion: defaultsVersion,
          updatedAt: serverTimestamp(),
        },
        { merge: true }
      );
    }

    returnedActive = sanitizedActive;
  } else if (defaultsVersion < PROMPT_DEFAULTS_VERSION) {
    const nextActive: ActivePromptSelections = { ...activeTemplates };
    let changed = false;

    for (const stage of SYSTEM_STAGES) {
      const selected = (nextActive[stage] as string | undefined) || DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY;
      if (!nextActive[stage] || selected === LEGACY_SYSTEM_PROMPT_TEMPLATE_KEY) {
        nextActive[stage] = DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY;
        changed = true;
      }
    }

    defaultsVersion = PROMPT_DEFAULTS_VERSION;
    changed = true;

    if (changed) {
      const settingsRef = doc(db, 'users', user.uid, 'promptSettings', 'active');
      await setDoc(
        settingsRef,
        {
          activeTemplates: nextActive,
          promptDefaultsVersion: defaultsVersion,
          updatedAt: serverTimestamp(),
        },
        { merge: true }
      );
    }

    returnedActive = nextActive;
  }

  return {
    templates,
    active: returnedActive,
    askOnEachProcess: Boolean(activeDoc.askOnEachProcess),
    systemTemplates,
    systemPermissions,
  };
}

export async function createPromptTemplate(payload: PromptTemplatePayload) {
  const user = await requireAuth();
  if (!user) {
    throw new Error('Not authenticated');
  }
  const db = await getFirestoreForUser();

  if (payload.name.length < MIN_NAME_LENGTH || payload.name.length > MAX_NAME_LENGTH) {
    throw new Error(`<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`);
  }

  const validationError = validatePlaceholders(payload.stage, payload.instructions);
  if (validationError) throw new Error(validationError);

  await ensureLimits(payload.stage, user.uid, db);

  const templatesRef = collection(db, 'users', user.uid, 'promptTemplates');
  const docRef = await addDoc(templatesRef, {
    stage: payload.stage,
    name: payload.name,
    instructions: payload.instructions,
    placeholders: STAGE_CONFIG[payload.stage].requiredPlaceholders,
    createdAt: serverTimestamp(),
    updatedAt: serverTimestamp(),
  });

  revalidatePath('/profil');
  return { id: docRef.id };
}

export async function updatePromptTemplate(id: string, payload: Omit<PromptTemplatePayload, 'stage'>) {
  const user = await requireAuth();
  if (!user) {
    throw new Error('Not authenticated');
  }
  const db = await getFirestoreForUser();

  if (payload.name.length < MIN_NAME_LENGTH || payload.name.length > MAX_NAME_LENGTH) {
    throw new Error(`<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`);
  }

  // Fetch to ensure stage not changed
  const ref = doc(db, 'users', user.uid, 'promptTemplates', id);
  const snapshot = await getDoc(ref);
  if (!snapshot.exists()) throw new Error('Template nicht gefunden.');
  const stage = (snapshot.data() as any).stage as PromptStage;

  const validationError = validatePlaceholders(stage, payload.instructions);
  if (validationError) throw new Error(validationError);

  await updateDoc(ref, {
    name: payload.name,
    instructions: payload.instructions,
    updatedAt: serverTimestamp(),
  });

  revalidatePath('/profil');
}

export async function deletePromptTemplate(id: string) {
  const user = await requireAuth();
  if (!user) {
    throw new Error('Not authenticated');
  }
  const db = await getFirestoreForUser();

  const ref = doc(db, 'users', user.uid, 'promptTemplates', id);
  const snapshot = await getDoc(ref);
  if (!snapshot.exists()) return;
  const stage = (snapshot.data() as any).stage as PromptStage;

  // Remove if active
  const settingsRef = doc(db, 'users', user.uid, 'promptSettings', 'active');
  const settingsSnap = await getDoc(settingsRef);
  if (settingsSnap.exists()) {
    const active = settingsSnap.data()?.activeTemplates || {};
    if (active[stage] === id) {
      await setDoc(
        settingsRef,
        {
          activeTemplates: { ...active, [stage]: DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY },
          updatedAt: serverTimestamp(),
        },
        { merge: true }
      );
    }
  }

  await deleteDoc(ref);
  revalidatePath('/profil');
}

export async function setActivePrompt(stage: PromptStage, templateId: string | 'default') {
  const user = await requireAuth();
  if (!user) {
    throw new Error('Not authenticated');
  }
  const db = await getFirestoreForUser();
  const settingsRef = doc(db, 'users', user.uid, 'promptSettings', 'active');
  const existing = await getDoc(settingsRef);
  const current = existing.exists() ? existing.data()?.activeTemplates || {} : {};
  await setDoc(
    settingsRef,
    {
      activeTemplates: { ...current, [stage]: templateId },
      updatedAt: serverTimestamp(),
    },
    { merge: true }
  );

  revalidatePath('/profil');
}

export async function setAskOnEachProcess(value: boolean) {
  const user = await requireAuth();
  if (!user) {
    throw new Error('Not authenticated');
  }
  const db = await getFirestoreForUser();
  const settingsRef = doc(db, 'users', user.uid, 'promptSettings', 'active');
  await setDoc(
    settingsRef,
    {
      askOnEachProcess: value,
      updatedAt: serverTimestamp(),
    },
    { merge: true }
  );
  revalidatePath('/profil');
}

export async function getActivePromptInstructions(stage: PromptStage): Promise<string> {
  const user = await requireAuth();
  if (!user) {
    throw new Error('Not authenticated');
  }
  const db = await getFirestoreForUser();
  const settingsRef = doc(db, 'users', user.uid, 'promptSettings', 'active');
  const settingsSnap = await getDoc(settingsRef);
  const active = settingsSnap.exists() ? settingsSnap.data()?.activeTemplates || {} : {};
  const activeId = active[stage];

  if (activeId && activeId !== 'default') {
    const ref = doc(db, 'users', user.uid, 'promptTemplates', activeId);
    const tpl = await getDoc(ref);
    if (tpl.exists()) {
      return (tpl.data() as any).instructions as string;
    }
  }

  return STAGE_CONFIG[stage].defaultInstructions;
}
