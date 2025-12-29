'use client';

import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

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
import { Switch } from '@/components/ui/switch';
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
import { STAGE_CONFIG } from '@/app/lib/prompts/promptConfig';
import type { PromptStage } from '@/app/types/prompts';
import { cn } from '@/lib/utils';
import { Archive, Pencil, Plus, RefreshCw } from 'lucide-react';

type AdminSystemPromptTemplate = {
  stage: PromptStage;
  templateKey: string;
  name: string;
  instructions: string;
  systemPrompt: string | null;
  published: boolean;
  archived: boolean;
  createdAt: string | null;
  updatedAt: string | null;
};

type EditorState = {
  isNew: boolean;
  stage: PromptStage;
  templateKey: string;
  name: string;
  instructions: string;
  systemPrompt: string;
  published: boolean;
  archived: boolean;
};

const stageOptions: { value: PromptStage; label: string }[] = [
  { value: 'process_quelle', label: STAGE_CONFIG.process_quelle.label },
  { value: 'combine', label: STAGE_CONFIG.combine.label },
  { value: 'shorten', label: STAGE_CONFIG.shorten.label },
  { value: 'lesefluss', label: STAGE_CONFIG.lesefluss.label },
  { value: 'summary', label: STAGE_CONFIG.summary.label },
];

const TEMPLATE_KEY_RE = /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/;

function isPromptStage(value: unknown): value is PromptStage {
  return typeof value === 'string' && stageOptions.some((s) => s.value === value);
}

function formatIso(iso: string | null): string {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleString('de-DE');
  } catch {
    return iso;
  }
}

function normalizeTemplate(input: any): AdminSystemPromptTemplate | null {
  const stage = input?.stage;
  const templateKey = input?.templateKey;
  if (!isPromptStage(stage) || typeof templateKey !== 'string') return null;

  return {
    stage,
    templateKey,
    name: typeof input?.name === 'string' ? input.name : templateKey,
    instructions: typeof input?.instructions === 'string' ? input.instructions : '',
    systemPrompt: typeof input?.systemPrompt === 'string' ? input.systemPrompt : null,
    published: input?.published === true,
    archived: input?.archived === true,
    createdAt: typeof input?.createdAt === 'string' ? input.createdAt : null,
    updatedAt: typeof input?.updatedAt === 'string' ? input.updatedAt : null,
  };
}

export function SystemPromptManager() {
  const [stage, setStage] = useState<PromptStage>('process_quelle');
  const [templates, setTemplates] = useState<AdminSystemPromptTemplate[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [editorOpen, setEditorOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [confirmArchive, setConfirmArchive] = useState<AdminSystemPromptTemplate | null>(null);

  const load = async () => {
    setIsLoading(true);
    try {
      const res = await fetch('/api/admin/system-prompt-templates', { cache: 'no-store' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Konnte System-Prompts nicht laden.');

      const raw = Array.isArray(data?.templates) ? data.templates : [];
      const normalized = raw.map(normalizeTemplate).filter(Boolean) as AdminSystemPromptTemplate[];
      normalized.sort((a, b) => {
        if (a.stage !== b.stage) return a.stage.localeCompare(b.stage, 'de');
        if (a.archived !== b.archived) return a.archived ? 1 : -1;
        if (a.published !== b.published) return a.published ? -1 : 1;
        return (b.updatedAt || '').localeCompare(a.updatedAt || '');
      });
      setTemplates(normalized);
    } catch (err: any) {
      toast.error('System-Prompts', { description: err?.message || 'Konnte System-Prompts nicht laden.' });
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const stageTemplates = useMemo(() => templates.filter((t) => t.stage === stage), [templates, stage]);
  const published = useMemo(
    () => stageTemplates.filter((t) => t.published && !t.archived),
    [stageTemplates]
  );
  const drafts = useMemo(
    () => stageTemplates.filter((t) => !t.published && !t.archived),
    [stageTemplates]
  );
  const archived = useMemo(() => stageTemplates.filter((t) => t.archived), [stageTemplates]);

  const missingPlaceholders = useMemo(() => {
    if (!editor) return [];
    return STAGE_CONFIG[editor.stage].requiredPlaceholders.filter((ph) => !editor.instructions.includes(ph));
  }, [editor]);

  const openNew = () => {
    setEditor({
      isNew: true,
      stage,
      templateKey: '',
      name: '',
      instructions: '',
      systemPrompt: '',
      published: false,
      archived: false,
    });
    setEditorOpen(true);
  };

  const openEdit = (tpl: AdminSystemPromptTemplate) => {
    setEditor({
      isNew: false,
      stage: tpl.stage,
      templateKey: tpl.templateKey,
      name: tpl.name,
      instructions: tpl.instructions,
      systemPrompt: tpl.systemPrompt || '',
      published: tpl.published,
      archived: tpl.archived,
    });
    setEditorOpen(true);
  };

  const save = async (state: EditorState) => {
    const name = state.name.trim();
    const templateKey = state.templateKey.trim();
    const instructions = state.instructions.replace(/\s+$/, '');
    const systemPrompt = state.systemPrompt.replace(/\s+$/, '');

    if (!name) throw new Error('Name ist erforderlich.');
    if (!templateKey) throw new Error('templateKey ist erforderlich.');
    if (!TEMPLATE_KEY_RE.test(templateKey)) {
      throw new Error("templateKey ungültig. Erlaubt: Buchstaben/Zahlen plus '-'/'_' (max. 64 Zeichen).");
    }
    if (!instructions.trim()) throw new Error('Instructions sind erforderlich.');

    setIsSaving(true);
    try {
      const res = await fetch('/api/admin/system-prompt-templates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          stage: state.stage,
          templateKey,
          name,
          instructions,
          systemPrompt,
          published: Boolean(state.published),
          archived: Boolean(state.archived),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Speichern fehlgeschlagen.');

      toast.success('System-Prompt gespeichert');
      setEditorOpen(false);
      setEditor(null);
      await load();
    } finally {
      setIsSaving(false);
    }
  };

  const quickToggle = async (tpl: AdminSystemPromptTemplate, next: Partial<Pick<AdminSystemPromptTemplate, 'published' | 'archived'>>) => {
    try {
      await save({
        isNew: false,
        stage: tpl.stage,
        templateKey: tpl.templateKey,
        name: tpl.name,
        instructions: tpl.instructions,
        systemPrompt: tpl.systemPrompt || '',
        published: typeof next.published === 'boolean' ? next.published : tpl.published,
        archived: typeof next.archived === 'boolean' ? next.archived : tpl.archived,
      });
    } catch (err: any) {
      toast.error('Aktion fehlgeschlagen', { description: err?.message || 'Unbekannter Fehler' });
    }
  };

  return (
    <div className="space-y-6">
      <Card className="p-5">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm font-medium text-foreground">System Prompt Templates</p>
            <p className="text-xs text-muted-foreground">
              Publizierte Templates sind sichtbar/auswählbar für Nutzer (ohne Text). Archivierte Templates werden automatisch ersetzt.
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Button variant="outline" size="sm" onClick={() => load()} disabled={isLoading}>
              <RefreshCw className="h-4 w-4 mr-1" />
              Refresh
            </Button>
            <Button size="sm" onClick={openNew}>
              <Plus className="h-4 w-4 mr-1" />
              Neuer Prompt
            </Button>
          </div>
        </div>
      </Card>

      <Tabs value={stage} onValueChange={(v) => setStage(v as PromptStage)}>
        <TabsList className="w-full flex-wrap h-auto gap-1 p-1">
          {stageOptions.map((opt) => {
            const count = templates.filter((t) => t.stage === opt.value && !t.archived).length;
            return (
              <TabsTrigger
                key={opt.value}
                value={opt.value}
                className="text-xs px-3 py-1.5 data-[state=active]:bg-primary data-[state=active]:text-primary-foreground"
              >
                {opt.label}
                {count > 0 && (
                  <Badge variant="secondary" className="ml-1.5 h-4 px-1 text-[10px]">
                    {count}
                  </Badge>
                )}
              </TabsTrigger>
            );
          })}
        </TabsList>

        {stageOptions.map((opt) => (
          <TabsContent key={opt.value} value={opt.value} className="mt-4 space-y-6">
            {isLoading ? (
              <Card className="p-6">
                <p className="text-sm text-muted-foreground">Lade System-Prompts…</p>
              </Card>
            ) : (
              <div className="space-y-6">
                <div className="space-y-2">
                  <p className="text-sm font-medium text-foreground">Published</p>
                  {published.length === 0 ? (
                    <Card className="p-6">
                      <p className="text-sm text-muted-foreground">Keine publizierten Templates.</p>
                    </Card>
                  ) : (
                    <div className="space-y-3">
                      {published.map((tpl) => (
                        <Card key={`${tpl.stage}:${tpl.templateKey}`} className="p-4 border-l-4 border-emerald-500">
                          <div className="flex items-start justify-between gap-4">
                            <div className="min-w-0">
                              <div className="flex items-center gap-2">
                                <p className="text-sm font-medium text-foreground truncate">{tpl.name}</p>
                                <Badge className="bg-emerald-600 text-white hover:bg-emerald-600">published</Badge>
                                <Badge variant="outline" className="font-mono text-[10px]">
                                  {tpl.templateKey}
                                </Badge>
                              </div>
                              <p className="text-xs text-muted-foreground mt-1">
                                updated: {formatIso(tpl.updatedAt)} · created: {formatIso(tpl.createdAt)}
                              </p>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                              <Button variant="outline" size="sm" onClick={() => openEdit(tpl)}>
                                <Pencil className="h-4 w-4 mr-1" />
                                Edit
                              </Button>
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => setConfirmArchive(tpl)}
                              >
                                <Archive className="h-4 w-4 mr-1" />
                                Archive
                              </Button>
                            </div>
                          </div>
                        </Card>
                      ))}
                    </div>
                  )}
                </div>

                <div className="space-y-2">
                  <p className="text-sm font-medium text-foreground">Drafts</p>
                  {drafts.length === 0 ? (
                    <Card className="p-6">
                      <p className="text-sm text-muted-foreground">Keine Drafts.</p>
                    </Card>
                  ) : (
                    <div className="space-y-3">
                      {drafts.map((tpl) => (
                        <Card key={`${tpl.stage}:${tpl.templateKey}`} className="p-4 border-l-4 border-amber-400">
                          <div className="flex items-start justify-between gap-4">
                            <div className="min-w-0">
                              <div className="flex items-center gap-2">
                                <p className="text-sm font-medium text-foreground truncate">{tpl.name}</p>
                                <Badge variant="secondary">draft</Badge>
                                <Badge variant="outline" className="font-mono text-[10px]">
                                  {tpl.templateKey}
                                </Badge>
                              </div>
                              <p className="text-xs text-muted-foreground mt-1">
                                updated: {formatIso(tpl.updatedAt)} · created: {formatIso(tpl.createdAt)}
                              </p>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                              <Button variant="outline" size="sm" onClick={() => openEdit(tpl)}>
                                <Pencil className="h-4 w-4 mr-1" />
                                Edit
                              </Button>
                              <Button
                                size="sm"
                                onClick={() => quickToggle(tpl, { published: true })}
                              >
                                Publish
                              </Button>
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => setConfirmArchive(tpl)}
                              >
                                <Archive className="h-4 w-4 mr-1" />
                                Archive
                              </Button>
                            </div>
                          </div>
                        </Card>
                      ))}
                    </div>
                  )}
                </div>

                <div className="space-y-2">
                  <p className="text-sm font-medium text-foreground">Archived</p>
                  {archived.length === 0 ? (
                    <Card className="p-6">
                      <p className="text-sm text-muted-foreground">Keine archivierten Templates.</p>
                    </Card>
                  ) : (
                    <div className="space-y-3">
                      {archived.map((tpl) => (
                        <Card key={`${tpl.stage}:${tpl.templateKey}`} className="p-4 border-l-4 border-zinc-400">
                          <div className="flex items-start justify-between gap-4">
                            <div className="min-w-0">
                              <div className="flex items-center gap-2">
                                <p className="text-sm font-medium text-foreground truncate">{tpl.name}</p>
                                <Badge variant="outline">archived</Badge>
                                <Badge variant="outline" className="font-mono text-[10px]">
                                  {tpl.templateKey}
                                </Badge>
                              </div>
                              <p className="text-xs text-muted-foreground mt-1">
                                updated: {formatIso(tpl.updatedAt)} · created: {formatIso(tpl.createdAt)}
                              </p>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                              <Button variant="outline" size="sm" onClick={() => openEdit(tpl)}>
                                <Pencil className="h-4 w-4 mr-1" />
                                View
                              </Button>
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => quickToggle(tpl, { archived: false })}
                              >
                                Restore
                              </Button>
                            </div>
                          </div>
                        </Card>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </TabsContent>
        ))}
      </Tabs>

      <Dialog open={editorOpen} onOpenChange={(open) => !isSaving && setEditorOpen(open)}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>{editor?.isNew ? 'Neuen System-Prompt erstellen' : 'System-Prompt bearbeiten'}</DialogTitle>
          </DialogHeader>

          {editor ? (
            <div className="space-y-5">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Stage</Label>
                  <Input value={STAGE_CONFIG[editor.stage].label} disabled />
                </div>
                <div className="space-y-2">
                  <Label>templateKey</Label>
                  <Input
                    value={editor.templateKey}
                    disabled={!editor.isNew}
                    onChange={(e) => setEditor((prev) => (prev ? { ...prev, templateKey: e.target.value } : prev))}
                    placeholder="z.B. default_v3"
                    className="font-mono"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label>Name</Label>
                <Input
                  value={editor.name}
                  onChange={(e) => setEditor((prev) => (prev ? { ...prev, name: e.target.value } : prev))}
                  placeholder="z.B. System-Standard (v3)"
                />
              </div>

              <div className="flex items-center justify-between gap-4">
                <div className="space-y-0.5">
                  <Label className="text-sm font-medium">Published</Label>
                  <p className="text-xs text-muted-foreground">Nur publizierte Templates sind für Nutzer sichtbar.</p>
                </div>
                <Switch
                  checked={editor.published}
                  onCheckedChange={(checked) => setEditor((prev) => (prev ? { ...prev, published: checked } : prev))}
                />
              </div>

              <div className="space-y-2">
                <Label>System Prompt (optional)</Label>
                <Textarea
                  value={editor.systemPrompt}
                  onChange={(e) => setEditor((prev) => (prev ? { ...prev, systemPrompt: e.target.value } : prev))}
                  placeholder="System role message (optional)"
                  className="min-h-[140px] font-mono text-xs"
                />
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between gap-4">
                  <Label>Instructions</Label>
                  {missingPlaceholders.length > 0 ? (
                    <Badge variant="secondary" className="text-[10px]">
                      Fehlende Platzhalter: {missingPlaceholders.join(', ')}
                    </Badge>
                  ) : (
                    <Badge className="bg-emerald-600 text-white hover:bg-emerald-600 text-[10px]">OK</Badge>
                  )}
                </div>
                <Textarea
                  value={editor.instructions}
                  onChange={(e) => setEditor((prev) => (prev ? { ...prev, instructions: e.target.value } : prev))}
                  placeholder="User instruction template"
                  className={cn(
                    'min-h-[220px] font-mono text-xs',
                    missingPlaceholders.length > 0 && 'border-amber-400 focus-visible:ring-amber-400'
                  )}
                />
              </div>
            </div>
          ) : null}

          <DialogFooter className="mt-4">
            <Button
              variant="outline"
              onClick={() => {
                if (isSaving) return;
                setEditorOpen(false);
                setEditor(null);
              }}
              disabled={isSaving}
            >
              Abbrechen
            </Button>
            <Button
              onClick={async () => {
                if (!editor) return;
                try {
                  await save(editor);
                } catch (err: any) {
                  toast.error('Speichern fehlgeschlagen', { description: err?.message || 'Unbekannter Fehler' });
                }
              }}
              disabled={!editor || isSaving}
            >
              {isSaving ? 'Speichern…' : 'Speichern'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={Boolean(confirmArchive)} onOpenChange={(open) => !open && setConfirmArchive(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Template archivieren?</AlertDialogTitle>
            <AlertDialogDescription>
              {confirmArchive
                ? `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`
                : null}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Abbrechen</AlertDialogCancel>
            <AlertDialogAction
              onClick={async () => {
                if (!confirmArchive) return;
                await quickToggle(confirmArchive, { archived: true, published: false });
                setConfirmArchive(null);
              }}
            >
              Archivieren
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
