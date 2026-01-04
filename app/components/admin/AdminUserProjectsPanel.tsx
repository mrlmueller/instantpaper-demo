'use client';

import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion';
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
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';

type ProjectRow = {
  id: string;
  name: string;
  archived: boolean;
  createdAt: string | null;
  updatedAt: string | null;
};

type ProjectsResponse = {
  projects: ProjectRow[];
  error?: string;
};

type QuelleMetaRow = {
  id: string;
  title: string;
  projektId: string;
  archived: boolean;
  wordCount: number;
  createdAt: string | null;
  updatedAt: string | null;
  autor?: string | null;
  jahr?: number | null;
  typ?: string | null;
  url?: string | null;
  zugriffAm?: string | null;
  zitat?: string | null;
  zitatModus?: string | null;
};

type QuellenResponse = {
  quellen: QuelleMetaRow[];
  error?: string;
};

type QuelleDetailResponse = {
  meta: QuelleMetaRow & { images?: unknown[] };
  content: { text: string | null; wordCount: number | null };
  error?: string;
};

function formatIso(iso: string | null): string {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleString('de-DE');
  } catch {
    return iso;
  }
}

export function AdminUserProjectsPanel({ uid }: { uid: string }) {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [openProjectId, setOpenProjectId] = useState<string | undefined>(undefined);
  const [quellenByProject, setQuellenByProject] = useState<Record<string, QuelleMetaRow[]>>({});
  const [loadingProjectId, setLoadingProjectId] = useState<string | null>(null);

  const [quelleDialogOpen, setQuelleDialogOpen] = useState(false);
  const [selectedQuelle, setSelectedQuelle] = useState<QuelleDetailResponse | null>(null);
  const [loadingQuelle, setLoadingQuelle] = useState(false);

  const loadProjects = async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/admin/users/${encodeURIComponent(uid)}/projects?include_archived=true`, {
        cache: 'no-store',
      });
      const data = (await res.json()) as ProjectsResponse;
      if (!res.ok) throw new Error((data as any)?.error || 'Konnte Projekte nicht laden.');
      setProjects(Array.isArray(data.projects) ? data.projects : []);
    } catch (err: any) {
      toast.error('Projekte', { description: err?.message || 'Konnte Projekte nicht laden.' });
      setProjects([]);
    } finally {
      setLoading(false);
    }
  };

  const loadQuellenForProject = async (projektId: string) => {
    if (!projektId) return;
    setLoadingProjectId(projektId);
    try {
      const res = await fetch(
        `/api/admin/users/${encodeURIComponent(uid)}/projects/${encodeURIComponent(projektId)}/quellen`,
        { cache: 'no-store' }
      );
      const data = (await res.json()) as QuellenResponse;
      if (!res.ok) throw new Error((data as any)?.error || 'Konnte Quellen nicht laden.');
      const list = Array.isArray(data.quellen) ? data.quellen : [];
      setQuellenByProject((prev) => ({ ...prev, [projektId]: list }));
    } catch (err: any) {
      toast.error('Quellen', { description: err?.message || 'Konnte Quellen nicht laden.' });
      setQuellenByProject((prev) => ({ ...prev, [projektId]: [] }));
    } finally {
      setLoadingProjectId(null);
    }
  };

  const openQuelle = async (quelleId: string) => {
    if (!quelleId) return;
    setLoadingQuelle(true);
    setQuelleDialogOpen(true);
    setSelectedQuelle(null);
    try {
      const res = await fetch(`/api/admin/users/${encodeURIComponent(uid)}/quellen/${encodeURIComponent(quelleId)}`, {
        cache: 'no-store',
      });
      const data = (await res.json()) as QuelleDetailResponse;
      if (!res.ok) throw new Error((data as any)?.error || 'Konnte Quelle nicht laden.');
      setSelectedQuelle(data);
    } catch (err: any) {
      toast.error('Quelle', { description: err?.message || 'Konnte Quelle nicht laden.' });
      setSelectedQuelle(null);
      setQuelleDialogOpen(false);
    } finally {
      setLoadingQuelle(false);
    }
  };

  useEffect(() => {
    loadProjects();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uid]);

  useEffect(() => {
    if (!openProjectId) return;
    if (quellenByProject[openProjectId]) return;
    loadQuellenForProject(openProjectId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openProjectId]);

  const projectCount = projects.length;
  const totalQuellenLoaded = useMemo(
    () => Object.values(quellenByProject).reduce((acc, list) => acc + (Array.isArray(list) ? list.length : 0), 0),
    [quellenByProject]
  );

  if (loading) {
    return (
      <Card className="p-6 space-y-3">
        <Skeleton className="h-5 w-48" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </Card>
    );
  }

  if (projects.length === 0) {
    return (
      <Card className="p-6">
        <p className="text-sm text-muted-foreground">Keine Projekte gefunden.</p>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card className="p-5 flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <div className="text-sm text-muted-foreground">
          {projectCount} Projekte • {totalQuellenLoaded} Quellen geladen
        </div>
        <Button variant="outline" size="sm" onClick={loadProjects} disabled={loading}>
          Reload projects
        </Button>
      </Card>

      <Accordion
        type="single"
        collapsible
        value={openProjectId}
        onValueChange={(v) => setOpenProjectId(v || undefined)}
      >
        {projects.map((p) => {
          const quellen = quellenByProject[p.id];
          const isLoadingQuellen = loadingProjectId === p.id;
          return (
            <AccordionItem key={p.id} value={p.id}>
              <AccordionTrigger>
                <div className="flex flex-wrap items-center gap-2 min-w-0">
                  <span className="truncate">{p.name}</span>
                  {p.archived ? <Badge variant="outline">archived</Badge> : null}
                  <span className="text-xs text-muted-foreground">({p.id})</span>
                </div>
              </AccordionTrigger>
              <AccordionContent>
                <Card className="p-4">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between mb-3">
                    <div className="text-xs text-muted-foreground">
                      Created: {formatIso(p.createdAt)} • Updated: {formatIso(p.updatedAt)}
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => loadQuellenForProject(p.id)}
                      disabled={isLoadingQuellen}
                    >
                      Reload Quellen
                    </Button>
                  </div>

                  {isLoadingQuellen ? (
                    <div className="space-y-2">
                      <Skeleton className="h-8 w-full" />
                      <Skeleton className="h-8 w-full" />
                    </div>
                  ) : !quellen ? (
                    <p className="text-sm text-muted-foreground">Lade Quellen…</p>
                  ) : quellen.length === 0 ? (
                    <p className="text-sm text-muted-foreground">Keine Quellen in diesem Projekt.</p>
                  ) : (
                    <div className="overflow-x-auto">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Titel</TableHead>
                            <TableHead>Wörter</TableHead>
                            <TableHead>Created</TableHead>
                            <TableHead className="text-right">Aktion</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {quellen.map((q) => (
                            <TableRow key={q.id}>
                              <TableCell className="font-medium">
                                <div className="flex items-center gap-2 min-w-0">
                                  <span className="truncate">{q.title}</span>
                                  {q.archived ? <Badge variant="outline">archived</Badge> : null}
                                </div>
                                {q.autor || q.jahr || q.typ ? (
                                  <div className="text-xs text-muted-foreground mt-1">
                                    {[q.autor, q.jahr ? String(q.jahr) : null, q.typ].filter(Boolean).join(' • ')}
                                  </div>
                                ) : null}
                              </TableCell>
                              <TableCell className="text-sm text-muted-foreground">{q.wordCount ?? 0}</TableCell>
                              <TableCell className="text-xs text-muted-foreground">{formatIso(q.createdAt)}</TableCell>
                              <TableCell className="text-right">
                                <Button variant="outline" size="sm" onClick={() => openQuelle(q.id)}>
                                  View
                                </Button>
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  )}
                </Card>
              </AccordionContent>
            </AccordionItem>
          );
        })}
      </Accordion>

      <Dialog open={quelleDialogOpen} onOpenChange={(open) => (!loadingQuelle ? setQuelleDialogOpen(open) : null)}>
        <DialogContent className="max-w-4xl">
          <DialogHeader>
            <DialogTitle>{selectedQuelle?.meta?.title || 'Quelle'}</DialogTitle>
          </DialogHeader>

          {loadingQuelle ? (
            <div className="space-y-3">
              <Skeleton className="h-4 w-48" />
              <Skeleton className="h-64 w-full" />
            </div>
          ) : !selectedQuelle ? (
            <p className="text-sm text-muted-foreground">Keine Daten.</p>
          ) : (
            <div className="space-y-4">
              <div className="text-xs text-muted-foreground space-y-1">
                <div>ID: {selectedQuelle.meta.id}</div>
                <div>Projekt: {selectedQuelle.meta.projektId}</div>
                <div>
                  Created: {formatIso(selectedQuelle.meta.createdAt)} • Updated: {formatIso(selectedQuelle.meta.updatedAt)}
                </div>
                {selectedQuelle.meta.url ? <div>URL: {selectedQuelle.meta.url}</div> : null}
                {selectedQuelle.meta.zitat ? <div>Zitat: {selectedQuelle.meta.zitat}</div> : null}
              </div>

              <Textarea
                readOnly
                value={selectedQuelle.content.text || ''}
                className="min-h-[360px] font-mono text-xs"
              />
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setQuelleDialogOpen(false)} disabled={loadingQuelle}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

