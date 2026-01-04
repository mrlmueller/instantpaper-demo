'use client';

import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { STAGE_CONFIG } from '@/app/lib/prompts/promptConfig';
import type { PromptStage, PromptTemplate, SystemPromptTemplateMeta } from '@/app/types/prompts';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';

type ListResponse = {
  templates: PromptTemplate[];
  active: Partial<Record<PromptStage, string>>;
  askOnEachProcess?: boolean;
  error?: string;
};

type SystemTemplatesResponse = {
  templates: Array<{
    stage: PromptStage;
    templateKey: string;
    name: string;
    published: boolean;
    archived: boolean;
    createdAt: string | null;
    updatedAt: string | null;
  }>;
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
    return new Date(iso).toLocaleString('de-DE');
  } catch {
    return iso;
  }
}

function truncate(s: string, max = 140): string {
  const txt = String(s || '').trim();
  if (txt.length <= max) return txt;
  return `${txt.slice(0, max).trim()}…`;
}

export function AdminUserPromptManager({ uid }: { uid: string }) {
  const [stage, setStage] = useState<PromptStage>('process_quelle');
  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [active, setActive] = useState<Partial<Record<PromptStage, string>>>({});
  const [systemTemplates, setSystemTemplates] = useState<SystemPromptTemplateMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [pendingActive, setPendingActive] = useState<string>('');
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
      const mapped = raw
        .filter((t) => t && t.published === true && t.archived !== true)
        .map((t) => ({
          stage: t.stage,
          templateKey: t.templateKey,
          name: t.name,
          createdAt: t.createdAt,
          updatedAt: t.updatedAt,
        }))
        .filter((t) => Boolean(t.stage) && Boolean(t.templateKey));

      setSystemTemplates(mapped);
    } catch (err: any) {
      // Defaults are always available; the dropdown will still work.
      setSystemTemplates([]);
    }
  };

  useEffect(() => {
    load();
    loadSystemTemplates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uid]);

  const stageTemplates = useMemo(() => {
    const list = templates.filter((t) => t.stage === stage);
    return list.sort((a, b) => (b.updatedAt || '').localeCompare(a.updatedAt || ''));
  }, [templates, stage]);

  const activeId = (active[stage] as string | undefined) || 'default';

  const systemOptionsForStage = useMemo(() => {
    const base: SystemPromptTemplateMeta[] = [
      { stage, templateKey: 'default', name: 'System-Standard', createdAt: null, updatedAt: null },
      { stage, templateKey: 'default_v2', name: 'System-Standard (v2)', createdAt: null, updatedAt: null },
    ];
    const additional = systemTemplates
      .filter((t) => t.stage === stage)
      .filter((t) => t.templateKey !== 'default' && t.templateKey !== 'default_v2');

    const merged = [...base, ...additional];
    const seen = new Set<string>();
    return merged.filter((t) => {
      const key = `${t.stage}:${t.templateKey}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }, [stage, systemTemplates]);

  useEffect(() => {
    setPendingActive(activeId);
  }, [activeId]);

  const missingForInstructions = (s: PromptStage, instructions: string): string[] => {
    const required = STAGE_CONFIG[s].requiredPlaceholders || [];
    return required.filter((ph) => !String(instructions || '').includes(ph));
  };

  const activeLabel = useMemo(() => {
    const foundUser = stageTemplates.find((t) => t.id === activeId);
    if (foundUser) return { label: foundUser.name, kind: 'user' as const };
    const foundSys = systemOptionsForStage.find((t) => t.templateKey === activeId);
    if (foundSys) return { label: foundSys.name, kind: 'system' as const };
    return { label: activeId, kind: 'system' as const };
  }, [activeId, stageTemplates, systemOptionsForStage]);

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
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = (await res.json()) as { id?: string; error?: string };
    if (!res.ok) throw new Error(data.error || 'Speichern fehlgeschlagen.');
    return data.id;
  };

  const apiUpdate = async (templateId: string, payload: { name: string; instructions: string }) => {
    const res = await fetch(`<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = (await res.json()) as { error?: string };
    if (!res.ok) throw new Error(data.error || 'Speichern fehlgeschlagen.');
  };

  const apiDelete = async (templateId: string) => {
    const res = await fetch(`<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`, {
      method: 'DELETE',
    });
    const data = (await res.json()) as { error?: string };
    if (!res.ok) throw new Error(data.error || 'Löschen fehlgeschlagen.');
  };

  const apiSetActive = async (targetStage: PromptStage, templateId: string) => {
    const res = await fetch(`<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stage: targetStage, templateId }),
    });
    const data = (await res.json()) as { error?: string };
    if (!res.ok) throw new Error(data.error || 'Aktiv setzen fehlgeschlagen.');
  };

  const confirmTitle = useMemo(() => {
    if (!confirm) return '';
    if (confirm.kind === 'setActive') return 'Aktives Prompt ändern?';
    if (confirm.kind === 'delete') return 'Prompt löschen?';
    if (confirm.kind === 'duplicate') return 'Prompt duplizieren?';
    return confirm.editor.id ? 'Prompt aktualisieren?' : 'Prompt anlegen?';
  }, [confirm]);

  const confirmDescription = useMemo(() => {
    if (!confirm) return '';
    if (confirm.kind === 'setActive') {
      return `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`;
    }
    if (confirm.kind === 'delete') {
      return `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`;
    }
    if (confirm.kind === 'duplicate') {
      return `Dupliziere: ${confirm.template.name}`;
    }
    const missing = missingForInstructions(confirm.editor.stage, confirm.editor.instructions);
    if (missing.length > 0) return `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`;
    return confirm.editor.id ? `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>` : `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`;
  }, [confirm]);

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
        const suffix = ' (Kopie)';
        const maxLen = 80;
        let name = `${confirm.template.name}${suffix}`;
        if (name.length > maxLen) name = name.slice(0, maxLen).trim();
        await apiCreate({ stage: confirm.template.stage, name, instructions: confirm.template.instructions });
        toast.success('Prompt dupliziert');
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

  const requestActiveChange = () => {
    if (!pendingActive || pendingActive === activeId) return;
    setConfirm({ kind: 'setActive', stage, templateId: pendingActive });
  };

  return (
    <div className="space-y-6">
      <Card className="p-5 space-y-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <p className="text-sm font-medium text-foreground">Aktives Prompt</p>
            <p className="text-xs text-muted-foreground">
              {activeLabel.kind === 'user' ? 'User Prompt' : 'System Prompt'}: {activeLabel.label}
            </p>
          </div>
          <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
            <Select value={pendingActive} onValueChange={setPendingActive}>
              <SelectTrigger className="w-full sm:w-[340px]">
                <SelectValue placeholder="Aktives Prompt wählen" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectLabel>System</SelectLabel>
                  {systemOptionsForStage.map((t) => (
                    <SelectItem key={`sys:${t.templateKey}`} value={t.templateKey}>
                      {t.name}
                      <span className="text-muted-foreground"> ({t.templateKey})</span>
                    </SelectItem>
                  ))}
                </SelectGroup>
                <SelectSeparator />
                <SelectGroup>
                  <SelectLabel>User Prompts</SelectLabel>
                  {stageTemplates.length === 0 ? (
                    <SelectItem value="__none__" disabled>
                      Keine User Prompts
                    </SelectItem>
                  ) : (
                    stageTemplates.map((t) => (
                      <SelectItem key={`user:${t.id}`} value={t.id}>
                        {t.name}
                      </SelectItem>
                    ))
                  )}
                </SelectGroup>
              </SelectContent>
            </Select>
            <Button onClick={requestActiveChange} disabled={saving || pendingActive === activeId || pendingActive === '__none__'}>
              Set active
            </Button>
          </div>
        </div>
      </Card>

      <Tabs value={stage} onValueChange={(v) => setStage(v as PromptStage)}>
        <TabsList className="w-full flex-wrap h-auto gap-1 p-1">
          {stageOptions.map((opt) => {
            const count = templates.filter((t) => t.stage === opt.value).length;
            return (
              <TabsTrigger key={opt.value} value={opt.value} className="text-xs px-3 py-1.5">
                {opt.label}
                {count > 0 ? (
                  <Badge variant="secondary" className="ml-1.5 h-4 px-1 text-[10px]">
                    {count}
                  </Badge>
                ) : null}
              </TabsTrigger>
            );
          })}
        </TabsList>

        <TabsContent value={stage} className="space-y-4 mt-4">
          <div className="flex items-center justify-between gap-3">
            <div className="text-sm text-muted-foreground">{loading ? 'Lade…' : `${stageTemplates.length} Prompts`}</div>
            <Button onClick={openNew} variant="outline" disabled={saving}>
              New prompt
            </Button>
          </div>

          {stageTemplates.length === 0 ? (
            <Card className="p-5">
              <p className="text-sm text-muted-foreground">Keine User Prompts in dieser Stage.</p>
            </Card>
          ) : (
            <div className="space-y-3">
              {stageTemplates.map((t) => {
                const isActive = activeId === t.id;
                const missing = missingForInstructions(t.stage, t.instructions);
                return (
                  <Card key={t.id} className="p-4">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-sm font-medium text-foreground truncate">{t.name}</p>
                          {isActive ? <Badge className="bg-emerald-600 text-white hover:bg-emerald-600">active</Badge> : null}
                          {missing.length > 0 ? (
                            <Badge variant="outline" className="border-destructive text-destructive">
                              missing placeholders
                            </Badge>
                          ) : null}
                        </div>
                        <p className="text-xs text-muted-foreground mt-1">{truncate(t.instructions)}</p>
                        <p className="text-[11px] text-muted-foreground mt-2">
                          Updated: {formatIso(t.updatedAt)} • ID: {t.id}
                        </p>
                      </div>

                      <div className="flex flex-wrap gap-2 justify-end">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setConfirm({ kind: 'setActive', stage: t.stage, templateId: t.id })}
                          disabled={saving || isActive}
                        >
                          Set active
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => openEdit(t)} disabled={saving}>
                          Edit
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => setConfirm({ kind: 'duplicate', template: t })} disabled={saving}>
                          Duplicate
                        </Button>
                        <Button
                          variant="destructive"
                          size="sm"
                          onClick={() => setConfirm({ kind: 'delete', templateId: t.id, name: t.name })}
                          disabled={saving}
                        >
                          Delete
                        </Button>
                      </div>
                    </div>
                  </Card>
                );
              })}
            </div>
          )}
        </TabsContent>
      </Tabs>

      <Dialog open={editorOpen} onOpenChange={(open) => (!saving ? setEditorOpen(open) : null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{editor?.id ? 'Edit Prompt' : 'New Prompt'}</DialogTitle>
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
            <AlertDialogTitle>{confirmTitle}</AlertDialogTitle>
            <AlertDialogDescription>{confirmDescription}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={saving}>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={runConfirm} disabled={saving}>
              Confirm
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
