'use client';

import * as AlertDialogPrimitive from '@radix-ui/react-alert-dialog';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Check, Copy, Pencil, Plus, Star, StarOff, Trash2 } from 'lucide-react';

import { STAGE_CONFIG } from '@/app/lib/prompts/promptConfig';
import type { PromptStage, PromptTemplate } from '@/app/types/prompts';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { cn } from '@/lib/utils';

type ListResponse = {
  templates: PromptTemplate[];
  active: Partial<Record<PromptStage, string>>;
  error?: string;
};

type AdminSystemPromptTemplate = {
  stage: PromptStage;
  templateKey: string;
  name: string;
  instructions: string;
  published: boolean;
  archived: boolean;
  createdAt: string | null;
  updatedAt: string | null;
};

type SystemTemplatesResponse = {
  templates: AdminSystemPromptTemplate[];
  error?: string;
};

type EditorState = {
  id?: string;
  stage: PromptStage;
  name: string;
  instructions: string;
};

type PendingAction =
  | { kind: 'setActive'; stage: PromptStage; templateId: string }
  | { kind: 'delete'; templateId: string; name: string }
  | { kind: 'duplicate'; template: PromptTemplate }
  | { kind: 'duplicateSystem'; stage: PromptStage; templateKey: string; name: string; instructions: string }
  | { kind: 'save'; editor: EditorState };

const stageOptions: { value: PromptStage; label: string }[] = [
  { value: 'process_quelle', label: STAGE_CONFIG.process_quelle.label },
  { value: 'combine', label: STAGE_CONFIG.combine.label },
  { value: 'shorten', label: STAGE_CONFIG.shorten.label },
  { value: 'lesefluss', label: STAGE_CONFIG.lesefluss.label },
  { value: 'summary', label: STAGE_CONFIG.summary.label },
];

function formatIso(iso: string | null): string {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleDateString('de-DE');
  } catch {
    return iso;
  }
}

function truncate(s: string, max = 160): string {
  const txt = String(s || '').trim();
  if (txt.length <= max) return txt;
  return `${txt.slice(0, max).trim()}…`;
}

function clampName(name: string): string {
  const maxLen = 80;
  const trimmed = String(name || '').trim();
  if (trimmed.length <= maxLen) return trimmed;
  return trimmed.slice(0, maxLen).trim();
}

export function AdminUserPromptManager({ uid, refreshNonce }: { uid: string; refreshNonce?: number }) {
  const [stage, setStage] = useState<PromptStage>('process_quelle');
  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [active, setActive] = useState<Partial<Record<PromptStage, string>>>({});
  const [systemTemplates, setSystemTemplates] = useState<AdminSystemPromptTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [confirm, setConfirm] = useState<PendingAction | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const res = await fetch(`<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`, { cache: 'no-store' });
      const data = (await res.json()) as ListResponse;
      if (!res.ok) throw new Error((data as any)?.error || 'Konnte Prompts nicht laden.');
      setTemplates(Array.isArray(data.templates) ? data.templates : []);
      setActive((data.active || {}) as any);
    } catch (err: any) {
      toast.error('Prompts', { description: err?.message || 'Konnte Prompts nicht laden.' });
      setTemplates([]);
      setActive({});
    } finally {
      setLoading(false);
    }
  };

  const loadSystemTemplates = async () => {
    try {
      const res = await fetch('/api/admin/system-prompt-templates', { cache: 'no-store' });
      const data = (await res.json()) as SystemTemplatesResponse;
      if (!res.ok) throw new Error((data as any)?.error || 'Konnte System-Prompts nicht laden.');

      const raw = Array.isArray(data.templates) ? data.templates : [];
      const filtered = raw
        .filter((t) => t && t.published === true && t.archived !== true)
        .filter((t) => Boolean(t.stage) && Boolean(t.templateKey))
        .map((t) => ({
          stage: t.stage,
          templateKey: t.templateKey,
          name: t.name,
          instructions: String(t.instructions || ''),
          published: t.published === true,
          archived: t.archived === true,
          createdAt: t.createdAt ?? null,
          updatedAt: t.updatedAt ?? null,
        }));

      setSystemTemplates(filtered);
    } catch {
      setSystemTemplates([]);
    }
  };

  useEffect(() => {
    load();
    loadSystemTemplates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uid, refreshNonce]);

  const stageTemplates = useMemo(() => {
    const list = templates.filter((t) => t.stage === stage);
    return list.sort((a, b) => (b.updatedAt || '').localeCompare(a.updatedAt || ''));
  }, [templates, stage]);

  const activeId = (active[stage] as string | undefined) || 'default';

  const systemOptionsForStage = useMemo(() => {
    const base: AdminSystemPromptTemplate[] = [
      {
        stage,
        templateKey: 'default',
        name: 'System-Standard',
        instructions: '',
        published: true,
        archived: false,
        createdAt: null,
        updatedAt: null,
      },
      {
        stage,
        templateKey: 'default_v2',
        name: 'System-Standard (v2)',
        instructions: '',
        published: true,
        archived: false,
        createdAt: null,
        updatedAt: null,
      },
    ];

    const byKey = new Map<string, AdminSystemPromptTemplate>();
    for (const tpl of base) byKey.set(tpl.templateKey, tpl);
    for (const tpl of systemTemplates.filter((t) => t.stage === stage)) byKey.set(tpl.templateKey, tpl);

    const merged = Array.from(byKey.values());
    const priority = (key: string) => (key === 'default' ? 0 : key === 'default_v2' ? 1 : 2);
    merged.sort((a, b) => priority(a.templateKey) - priority(b.templateKey) || a.name.localeCompare(b.name, 'de'));
    return merged;
  }, [stage, systemTemplates]);

  const requiredPlaceholders = STAGE_CONFIG[stage].requiredPlaceholders.join(', ');

  const missingForInstructions = (s: PromptStage, instructions: string): string[] => {
    const required = STAGE_CONFIG[s].requiredPlaceholders || [];
    return required.filter((ph) => !String(instructions || '').includes(ph));
  };

  const openNew = () => {
    setEditor({
      stage,
      name: '',
      instructions: STAGE_CONFIG[stage].defaultInstructions,
    });
    setEditorOpen(true);
  };

  const openEdit = (tpl: PromptTemplate) => {
    setEditor({
      id: tpl.id,
      stage: tpl.stage,
      name: tpl.name,
      instructions: tpl.instructions,
    });
    setEditorOpen(true);
  };

  const apiCreate = async (payload: { stage: PromptStage; name: string; instructions: string }) => {
    const res = await fetch(`<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = (await res.json()) as { id?: string; error?: string };
    if (!res.ok) throw new Error(data.error || "Speichern fehlgeschlagen.");
    return data.id;
  };

  const apiUpdate = async (templateId: string, payload: { name: string; instructions: string }) => {
    const res = await fetch(`<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = (await res.json()) as { error?: string };
    if (!res.ok) throw new Error(data.error || "Speichern fehlgeschlagen.");
  };

  const apiDelete = async (templateId: string) => {
    const res = await fetch(`<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`, {
      method: "DELETE",
    });
    const data = (await res.json()) as { error?: string };
    if (!res.ok) throw new Error(data.error || "Löschen fehlgeschlagen.");
  };

  const apiSetActive = async (targetStage: PromptStage, templateId: string) => {
    const res = await fetch(`<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage: targetStage, templateId }),
    });
    const data = (await res.json()) as { error?: string };
    if (!res.ok) throw new Error(data.error || "Aktiv setzen fehlgeschlagen.");
  };

  const confirmMeta = useMemo(() => {
    if (!confirm) return null;

    if (confirm.kind === 'delete') {
      return {
        title: 'Prompt löschen?',
        description: `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`,
        buttonLabel: 'Löschen',
        buttonVariant: 'destructive' as const,
      };
    }

    if (confirm.kind === 'setActive') {
      const stageLabel = STAGE_CONFIG[confirm.stage].label;
      const userTpl = templates.find((t) => t.stage === confirm.stage && t.id === confirm.templateId);
      const sysTpl = systemTemplates.find((t) => t.stage === confirm.stage && t.templateKey === confirm.templateId);
      const sysFallback =
        confirm.templateId === 'default'
          ? 'System-Standard'
          : confirm.templateId === 'default_v2'
            ? 'System-Standard (v2)'
            : null;
      const targetLabel = userTpl?.name || sysTpl?.name || sysFallback || confirm.templateId;
      return {
        title: 'Aktives Prompt ändern?',
        description: `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`,
        buttonLabel: 'Ändern',
        buttonVariant: 'default' as const,
      };
    }

    if (confirm.kind === 'duplicate') {
      return {
        title: 'Prompt duplizieren?',
        description: `Dupliziere: ${confirm.template.name}`,
        buttonLabel: 'Duplizieren',
        buttonVariant: 'default' as const,
      };
    }

    if (confirm.kind === 'duplicateSystem') {
      return {
        title: 'System-Prompt kopieren?',
        description: `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`,
        buttonLabel: 'Kopieren',
        buttonVariant: 'default' as const,
      };
    }

    const missing = missingForInstructions(confirm.editor.stage, confirm.editor.instructions);
    return {
      title: confirm.editor.id ? 'Prompt aktualisieren?' : 'Prompt anlegen?',
      description: missing.length > 0 ? `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>` : confirm.editor.name,
      buttonLabel: confirm.editor.id ? 'Speichern' : 'Anlegen',
      buttonVariant: 'default' as const,
    };
  }, [confirm, templates, systemTemplates]);

  const runConfirm = async () => {
    if (!confirm) return;
    setSaving(true);
    try {
      if (confirm.kind === 'setActive') {
        await apiSetActive(confirm.stage, confirm.templateId);
        toast.success('Aktives Prompt gesetzt');
      } else if (confirm.kind === 'delete') {
        await apiDelete(confirm.templateId);
        toast.success('Prompt gelöscht');
      } else if (confirm.kind === 'duplicate') {
        const name = clampName(`${confirm.template.name} (Kopie)`);
        await apiCreate({ stage: confirm.template.stage, name, instructions: confirm.template.instructions });
        toast.success('Prompt dupliziert');
      } else if (confirm.kind === 'duplicateSystem') {
        const name = clampName(`${confirm.name} (Kopie)`);
        if (!confirm.instructions.trim()) throw new Error('System-Template hat keine Instructions.');
        await apiCreate({ stage: confirm.stage, name, instructions: confirm.instructions });
        toast.success('Prompt kopiert');
      } else if (confirm.kind === 'save') {
        const state = confirm.editor;
        if (state.id) {
          await apiUpdate(state.id, { name: state.name, instructions: state.instructions });
          toast.success('Prompt aktualisiert');
        } else {
          await apiCreate({ stage: state.stage, name: state.name, instructions: state.instructions });
          toast.success('Prompt angelegt');
        }
        setEditorOpen(false);
        setEditor(null);
      }

      setConfirm(null);
      await load();
    } catch (err: any) {
      toast.error('Admin', { description: err?.message || 'Aktion fehlgeschlagen.' });
    } finally {
      setSaving(false);
    }
  };

  const requestSave = () => {
    if (!editor) return;
    const name = editor.name.trim();
    const instructions = editor.instructions.trim();
    if (!name || !instructions) {
      toast.error('Name und Instructions dürfen nicht leer sein.');
      return;
    }

    const missing = missingForInstructions(editor.stage, instructions);
    if (missing.length > 0) {
      toast.error('Pflicht-Platzhalter fehlen', { description: missing.join(', ') });
      return;
    }

    setConfirm({ kind: 'save', editor: { ...editor, name, instructions } });
  };

  const stageCounts = useMemo(() => {
    const counts: Partial<Record<PromptStage, number>> = {};
    for (const opt of stageOptions) counts[opt.value] = 0;
    for (const tpl of templates) counts[tpl.stage] = (counts[tpl.stage] || 0) + 1;
    return counts;
  }, [templates]);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-foreground">Prompt-Bibliothek</h2>
          <p className="text-sm text-muted-foreground">Prompts des Users verwalten</p>
        </div>
        <Button onClick={openNew} disabled={saving} className="shrink-0">
          <Plus className="h-4 w-4" />
          Neuer Prompt
        </Button>
      </div>

      <div>
        <div className="flex flex-wrap items-center gap-6 border-b">
          {stageOptions.map((opt) => {
            const count = stageCounts[opt.value] || 0;
            const isActive = stage === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => setStage(opt.value)}
                className={cn(
                  'flex items-center gap-2 pb-3 text-sm font-medium border-b-2 -mb-px transition-colors',
                  isActive
                    ? 'border-primary text-foreground'
                    : 'border-transparent text-muted-foreground hover:text-foreground'
                )}
              >
                <span>{opt.label}</span>
                {count > 0 ? (
                  <Badge variant="secondary" className="rounded-md px-2 py-0.5 text-xs font-semibold">
                    {count}
                  </Badge>
                ) : null}
              </button>
            );
          })}
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          Pflicht-Platzhalter: <span className="font-mono">{requiredPlaceholders}</span>
        </p>
      </div>

      {loading ? (
        <div className="space-y-3">
          {[...Array(4)].map((_, idx) => (
            <div key={idx} className="rounded-lg border bg-background px-4 py-3">
              <Skeleton className="h-4 w-56" />
              <Skeleton className="h-3 w-80 mt-2" />
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-3">
          {systemOptionsForStage.map((sys) => {
            const isActive = activeId === sys.templateKey;
            const canCopy = Boolean(sys.instructions && sys.instructions.trim());
            return (
              <div
                key={`sys:${sys.stage}:${sys.templateKey}`}
                className={cn(
                  'rounded-lg border bg-background px-4 py-3 shadow-sm transition-colors',
                  isActive && 'ring-2 ring-primary/40 bg-primary/5'
                )}
              >
                <div className="flex items-center justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-medium text-foreground truncate">{sys.name}</p>
                      <Badge variant="outline" className="rounded-md px-2 py-0.5 font-mono text-[11px]">
                        {sys.templateKey}
                      </Badge>
                      {isActive ? (
                        <Badge variant="default" className="rounded-md px-2 py-0.5 text-[11px] font-semibold bg-primary text-primary-foreground">
                          Standard
                        </Badge>
                      ) : null}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() =>
                        setConfirm({
                          kind: 'duplicateSystem',
                          stage,
                          templateKey: sys.templateKey,
                          name: sys.name,
                          instructions: sys.instructions,
                        })
                      }
                      disabled={saving || !canCopy}
                      title={canCopy ? 'In eigene Prompts kopieren' : 'Nicht verfügbar'}
                    >
                      <Copy className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() => setConfirm({ kind: 'setActive', stage, templateId: sys.templateKey })}
                      disabled={saving || isActive}
                      title={isActive ? 'Aktiv' : 'Als Standard setzen'}
                    >
                      {isActive ? <Check className="h-4 w-4 text-primary" /> : <Star className="h-4 w-4" />}
                    </Button>
                  </div>
                </div>
              </div>
            );
          })}

          {stageTemplates.length === 0 ? (
            <div className="rounded-lg border bg-background p-6 text-center">
              <p className="text-sm text-muted-foreground">Keine eigenen Prompts in dieser Stufe.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {stageTemplates.map((tpl) => {
                const isActive = activeId === tpl.id;
                const missing = missingForInstructions(tpl.stage, tpl.instructions);
                return (
                  <div
                    key={tpl.id}
                    className={cn(
                      'rounded-lg border bg-background px-4 py-3 shadow-sm transition-colors',
                      isActive && 'ring-2 ring-primary/40 bg-primary/5'
                    )}
                  >
                    <div className="flex items-start gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-sm font-medium text-foreground truncate">{tpl.name}</p>
                          {missing.length > 0 ? (
                            <Badge variant="outline" className="rounded-md px-2 py-0.5 text-[11px] border-destructive text-destructive">
                              Platzhalter fehlen
                            </Badge>
                          ) : null}
                        </div>
                        <p className="text-xs text-muted-foreground mt-1 line-clamp-2 font-mono">
                          {truncate(tpl.instructions)}
                        </p>
                        <p className="text-[11px] text-muted-foreground mt-2">Erstellt: {formatIso(tpl.createdAt)}</p>
                      </div>

                      <div className="flex items-center gap-1 shrink-0">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          onClick={() =>
                            setConfirm({ kind: 'setActive', stage: tpl.stage, templateId: isActive ? 'default' : tpl.id })
                          }
                          disabled={saving}
                          title={isActive ? 'Standard entfernen' : 'Als Standard setzen'}
                        >
                          {isActive ? <StarOff className="h-4 w-4 text-primary" /> : <Star className="h-4 w-4" />}
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          onClick={() => openEdit(tpl)}
                          disabled={saving}
                          title="Bearbeiten"
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          onClick={() => setConfirm({ kind: 'duplicate', template: tpl })}
                          disabled={saving}
                          title="Duplizieren"
                        >
                          <Copy className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-destructive hover:text-destructive"
                          onClick={() => setConfirm({ kind: 'delete', templateId: tpl.id, name: tpl.name })}
                          disabled={saving}
                          title="Löschen"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      <Dialog open={editorOpen} onOpenChange={(open) => (!saving ? setEditorOpen(open) : null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{editor?.id ? 'Prompt bearbeiten' : 'Neuer Prompt'}</DialogTitle>
          </DialogHeader>
          {editor ? (
            <div className="space-y-4">
              <div className="grid gap-2">
                <Label htmlFor="admin-prompt-name">Name</Label>
                <Input
                  id="admin-prompt-name"
                  value={editor.name}
                  maxLength={80}
                  onChange={(e) => setEditor((prev) => (prev ? { ...prev, name: e.target.value } : prev))}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="admin-prompt-instructions">Instructions</Label>
                <Textarea
                  id="admin-prompt-instructions"
                  value={editor.instructions}
                  className="min-h-[260px]"
                  onChange={(e) => setEditor((prev) => (prev ? { ...prev, instructions: e.target.value } : prev))}
                />
                {missingForInstructions(editor.stage, editor.instructions).length > 0 ? (
                  <p className="text-xs text-destructive">
                    Missing: {missingForInstructions(editor.stage, editor.instructions).join(', ')}
                  </p>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    Required placeholders: {STAGE_CONFIG[editor.stage].requiredPlaceholders.join(', ')}
                  </p>
                )}
              </div>
            </div>
          ) : null}
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setEditorOpen(false)} disabled={saving}>
              Cancel
            </Button>
            <Button onClick={requestSave} disabled={saving || !editor}>
              {editor?.id ? 'Save changes' : 'Create'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={Boolean(confirm)} onOpenChange={(open) => (!open ? setConfirm(null) : null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirmMeta?.title || ''}</AlertDialogTitle>
            <AlertDialogDescription>{confirmMeta?.description || ''}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={saving}>Abbrechen</AlertDialogCancel>
            <AlertDialogPrimitive.Action asChild>
              <Button
                variant={confirmMeta?.buttonVariant || 'destructive'}
                onClick={runConfirm}
                disabled={saving || !confirmMeta}
              >
                {confirmMeta?.buttonLabel || 'Bestätigen'}
              </Button>
            </AlertDialogPrimitive.Action>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

