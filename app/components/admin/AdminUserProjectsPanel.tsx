'use client';

import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { ExternalLink } from 'lucide-react';

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
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

function formatNumber(num: number): string {
  const n = Number(num || 0);
  if (!Number.isFinite(n)) return '0';
  return n.toLocaleString('de-DE');
}

export function AdminUserProjectsPanel({ uid, refreshNonce }: { uid: string; refreshNonce?: number }) {
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
      setQuellenByProject({});
      setOpenProjectId(undefined);
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
  }, [uid, refreshNonce]);

  useEffect(() => {
    if (!openProjectId) return;
    if (quellenByProject[openProjectId]) return;
    loadQuellenForProject(openProjectId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openProjectId]);

  const totalQuellenLoaded = useMemo(() => Object.values(quellenByProject).reduce((acc, list) => acc + list.length, 0), [quellenByProject]);

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="rounded-lg border bg-background p-6">
          <Skeleton className="h-5 w-56" />
          <Skeleton className="h-4 w-40 mt-2" />
        </div>
        <div className="space-y-2">
          {[...Array(2)].map((_, i) => (
            <div key={i} className="rounded-lg border bg-background px-4 py-3">
              <Skeleton className="h-4 w-64" />
              <Skeleton className="h-3 w-40 mt-2" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-foreground">Projekte & Quellen</h3>
        <p className="text-sm text-muted-foreground">
          {projects.length} Projekte • {totalQuellenLoaded} Quellen geladen
        </p>
      </div>

      {projects.length === 0 ? (
        <div className="rounded-lg border bg-background p-6">
          <p className="text-sm text-muted-foreground">Keine Projekte gefunden.</p>
        </div>
      ) : (
        <Accordion type="single" collapsible value={openProjectId} onValueChange={setOpenProjectId}>
          {projects.map((p) => {
            const quellen = quellenByProject[p.id];
            const count = typeof quellen === 'undefined' ? '—' : String(quellen.length);
            const isLoadingQuellen = loadingProjectId === p.id;

            return (
              <AccordionItem key={p.id} value={p.id} className="border-b-0 mb-4 last:mb-0">
                <div className="rounded-lg border bg-background px-4">
                  <AccordionTrigger className="hover:no-underline py-4">
                    <div className="flex items-center justify-between w-full gap-4">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="truncate">{p.name || p.id}</span>
                        {p.archived ? <Badge variant="outline">archived</Badge> : null}
                      </div>
                      <div className="text-xs text-muted-foreground shrink-0">{count} Quellen</div>
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="pb-4">
                    {isLoadingQuellen ? (
                      <div className="space-y-2">
                        <Skeleton className="h-10 w-full" />
                        <Skeleton className="h-10 w-full" />
                      </div>
                    ) : !quellen ? (
                      <p className="text-sm text-muted-foreground">Lade Quellen…</p>
                    ) : quellen.length === 0 ? (
                      <p className="text-sm text-muted-foreground">Keine Quellen in diesem Projekt.</p>
                    ) : (
                      <div className="space-y-2">
                        {quellen.map((q) => {
                          const meta = [
                            q.wordCount ? `${formatNumber(q.wordCount)} Wörter` : null,
                            q.autor || null,
                            typeof q.jahr === 'number' ? String(q.jahr) : null,
                            q.typ || null,
                          ]
                            .filter(Boolean)
                            .join(' • ');

                          return (
                            <div key={q.id} className="rounded-md border bg-background px-3 py-2">
                              <div className="flex items-center justify-between gap-3">
                                <div className="min-w-0">
                                  <p className="text-sm font-medium text-foreground truncate">{q.title || q.id}</p>
                                  {meta ? <p className="text-xs text-muted-foreground truncate">{meta}</p> : null}
                                </div>
                                <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => openQuelle(q.id)} aria-label="Quelle ansehen">
                                  <ExternalLink className="h-4 w-4" />
                                </Button>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </AccordionContent>
                </div>
              </AccordionItem>
            );
          })}
        </Accordion>
      )}

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
            <Textarea readOnly value={selectedQuelle.content.text || ''} className="min-h-[360px] font-mono text-xs" />
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

