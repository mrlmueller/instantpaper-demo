'use server';

import { revalidatePath } from 'next/cache';
import { getFirestoreForUser } from '@/app/lib/firebase/serverApp';
import { requireAuth } from '@/app/lib/auth/server-auth';
import type {
  ActivePromptSelections,
  PromptStage,
  PromptTemplate,
  PromptTemplatePayload,
  StageDefaultPromptTemplates,
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
  deleteField,
} from 'firebase/firestore';
import { buildFastApiUrl } from '@/app/lib/server/fastapi';

function validatePlaceholders(stage: PromptStage, instructions: string): string | null {
  const config = STAGE_CONFIG[stage];
  const missing = (config.requiredPlaceholders || []).filter((ph) => !instructions.includes(ph));
  if (missing.length > 0) {
    return `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`;
  }
  return null;
}

const SYSTEM_STAGES: PromptStage[] = ['process_quelle', 'combine', 'shorten', 'lesefluss', 'summary', 'gliederung'];
const PROMPT_DEFAULTS_VERSION = 3;

function fallbackSystemTemplates(): SystemPromptTemplateMeta[] {
  // Fail closed: if we can't reach the backend, don't guess which system templates exist
  // (archived templates must not become selectable due to a transient error).
  return [];
}

async function loadSystemTemplates(): Promise<{
  systemTemplates: SystemPromptTemplateMeta[];
  systemPermissions: SystemPromptPermissions;
  stageDefaults: StageDefaultPromptTemplates;
  source: 'backend' | 'fallback';
}> {
  const store = await cookies();
  const token = store.get('__session')?.value;
  if (!token) {
    return {
      systemTemplates: fallbackSystemTemplates(),
      systemPermissions: { canDuplicateSystemPrompts: false },
      stageDefaults: {},
      source: 'fallback',
    };
  }

  try {
    const res = await fetch(buildFastApiUrl('/api/system-prompt-templates'), {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      return {
        systemTemplates: fallbackSystemTemplates(),
        systemPermissions: { canDuplicateSystemPrompts: false },
        stageDefaults: {},
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

    const stageDefaults: StageDefaultPromptTemplates = {};
    const rawDefaults = (data as any)?.stageDefaults;
    if (rawDefaults && typeof rawDefaults === 'object') {
      for (const st of SYSTEM_STAGES) {
        const key = (rawDefaults as any)[st];
        if (typeof key === 'string' && key.trim()) stageDefaults[st] = key.trim();
      }
    }

    return {
      systemTemplates: templates,
      systemPermissions: { canDuplicateSystemPrompts: canDuplicate },
      stageDefaults,
      source: 'backend',
    };
  } catch {
    return {
      systemTemplates: fallbackSystemTemplates(),
      systemPermissions: { canDuplicateSystemPrompts: false },
      stageDefaults: {},
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
  stageDefaults: StageDefaultPromptTemplates;
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

  const { systemTemplates, systemPermissions, stageDefaults, source } = await loadSystemTemplates();

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
    const settingsRef = doc(db, 'users', user.uid, 'promptSettings', 'active');
    const patch: Record<string, any> = { updatedAt: serverTimestamp() };

    for (const stage of SYSTEM_STAGES) {
      const userIds = userTemplateIdsByStage.get(stage) || new Set<string>();
      const systemKeys = systemKeysByStage.get(stage) || new Set<string>();

      const raw = sanitizedActive[stage] as unknown;
      const selected = typeof raw === 'string' ? raw.trim() : raw != null ? String(raw).trim() : '';

      // One-time migration (v3): clear implicit defaults so admin defaults can apply.
      if (
        defaultsVersion < PROMPT_DEFAULTS_VERSION &&
        selected &&
        (selected === LEGACY_SYSTEM_PROMPT_TEMPLATE_KEY || selected === DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY)
      ) {
        delete sanitizedActive[stage];
        patch[`activeTemplates.${stage}`] = deleteField();
        changed = true;
        continue;
      }

      // Keep empty (unset): fall back to admin/system defaults at runtime.
      if (!selected) {
        continue;
      }

      // Keep valid user templates.
      if (selected !== LEGACY_SYSTEM_PROMPT_TEMPLATE_KEY && userIds.has(selected)) {
        continue;
      }

      // Keep currently selectable system templates.
      if (systemKeys.has(selected)) {
        continue;
      }

      // Invalid selection (deleted template or no longer selectable system key) -> fall back to newest system template.
      const fallbackKey =
        pickNewestSystemTemplateKeyForStage(stage, systemTemplates) || DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY;
      if (fallbackKey !== selected) {
        sanitizedActive[stage] = fallbackKey;
        patch[`activeTemplates.${stage}`] = fallbackKey;
        changed = true;
      }
    }

    if (defaultsVersion < PROMPT_DEFAULTS_VERSION) {
      defaultsVersion = PROMPT_DEFAULTS_VERSION;
      patch.promptDefaultsVersion = defaultsVersion;
      changed = true;
    }

    if (changed) {
      if (settingsDoc.exists()) {
        await updateDoc(settingsRef, patch);
      } else {
        await setDoc(
          settingsRef,
          {
            activeTemplates: sanitizedActive,
            promptDefaultsVersion: defaultsVersion,
            createdAt: serverTimestamp(),
            updatedAt: serverTimestamp(),
          },
          { merge: true }
        );
      }
    }

    returnedActive = sanitizedActive;
  } else if (defaultsVersion < PROMPT_DEFAULTS_VERSION) {
    const nextActive: ActivePromptSelections = { ...activeTemplates };
    let changed = false;
    const settingsRef = doc(db, 'users', user.uid, 'promptSettings', 'active');
    const patch: Record<string, any> = {
      updatedAt: serverTimestamp(),
      promptDefaultsVersion: PROMPT_DEFAULTS_VERSION,
    };

    for (const stage of SYSTEM_STAGES) {
      const raw = nextActive[stage] as unknown;
      const selected = typeof raw === 'string' ? raw.trim() : raw != null ? String(raw).trim() : '';

      if (selected && (selected === LEGACY_SYSTEM_PROMPT_TEMPLATE_KEY || selected === DEFAULT_SYSTEM_PROMPT_TEMPLATE_KEY)) {
        delete nextActive[stage];
        patch[`activeTemplates.${stage}`] = deleteField();
        changed = true;
      }
    }

    defaultsVersion = PROMPT_DEFAULTS_VERSION;
    changed = true;

    if (changed) {
      if (settingsDoc.exists()) {
        await updateDoc(settingsRef, patch);
      } else {
        await setDoc(
          settingsRef,
          {
            activeTemplates: nextActive,
            promptDefaultsVersion: defaultsVersion,
            createdAt: serverTimestamp(),
            updatedAt: serverTimestamp(),
          },
          { merge: true }
        );
      }
    }

    returnedActive = nextActive;
  }

  return {
    templates,
    active: returnedActive,
    askOnEachProcess: Boolean(activeDoc.askOnEachProcess),
    systemTemplates,
    systemPermissions,
    stageDefaults,
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
      await updateDoc(settingsRef, {
        [`activeTemplates.${stage}`]: deleteField(),
        promptDefaultsVersion: PROMPT_DEFAULTS_VERSION,
        updatedAt: serverTimestamp(),
      });
    }
  }

  await deleteDoc(ref);
  revalidatePath('/profil');
}

export async function setActivePrompt(stage: PromptStage, templateId: string | null) {
  const user = await requireAuth();
  if (!user) {
    throw new Error('Not authenticated');
  }
  const db = await getFirestoreForUser();
  const settingsRef = doc(db, 'users', user.uid, 'promptSettings', 'active');
  const existing = await getDoc(settingsRef);
  const current = existing.exists() ? existing.data()?.activeTemplates || {} : {};

  if (typeof templateId !== 'string' || !templateId.trim()) {
    if (existing.exists()) {
      await updateDoc(settingsRef, {
        [`activeTemplates.${stage}`]: deleteField(),
        promptDefaultsVersion: PROMPT_DEFAULTS_VERSION,
        updatedAt: serverTimestamp(),
      });
    } else {
      await setDoc(
        settingsRef,
        {
          activeTemplates: {},
          promptDefaultsVersion: PROMPT_DEFAULTS_VERSION,
          createdAt: serverTimestamp(),
          updatedAt: serverTimestamp(),
        },
        { merge: true }
      );
    }
  } else {
    await setDoc(
      settingsRef,
      {
        activeTemplates: { ...current, [stage]: templateId.trim() },
        promptDefaultsVersion: PROMPT_DEFAULTS_VERSION,
        updatedAt: serverTimestamp(),
      },
      { merge: true }
    );
  }

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
