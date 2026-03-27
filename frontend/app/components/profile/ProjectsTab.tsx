"use client";

import { useEffect, useMemo, useState } from "react";
import { collection, onSnapshot, orderBy, query } from "firebase/firestore";
import { toast } from "sonner";
import {
  Archive,
  FolderOpen,
  Loader2,
  Pencil,
  RotateCcw,
  Trash2,
} from "lucide-react";

import { firestoreClient } from "@/app/lib/firebase/firestoreClient";
import { renameProject, unarchiveProject } from "@/app/actions/projects";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type ProjectDoc = {
  name?: unknown;
  createdAt?: unknown;
  updatedAt?: unknown;
  archived?: unknown;
};

type ProjectRow = {
  id: string;
  name: string;
  createdAt: Date;
  updatedAt: Date | null;
  archived: boolean;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function toDate(value: unknown): Date | null {
  if (!value) return null;
  if (value instanceof Date) return value;
  if (typeof value === "string") {
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  if (
    typeof value === "object" &&
    value !== null &&
    "toDate" in value &&
    typeof (value as { toDate?: unknown }).toDate === "function"
  ) {
    const d = (value as { toDate: () => unknown }).toDate();
    return d instanceof Date ? d : null;
  }
  return null;
}

function formatDate(value: Date | null): string {
  if (!value) return "-";
  return value.toLocaleDateString("de-DE");
}

function normalizeName(value: string): string {
  return value.normalize("NFKC").trim().replace(/\s+/g, " ");
}

export function ProjectsTab({ userId }: { userId: string }) {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [loading, setLoading] = useState(true);

  const [renameDialogOpen, setRenameDialogOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<ProjectRow | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [renameSaving, setRenameSaving] = useState(false);

  const [deleteOpenProjectId, setDeleteOpenProjectId] = useState<string | null>(null);
  const [deleteConfirmValue, setDeleteConfirmValue] = useState("");
  const [deleteLoadingProjectId, setDeleteLoadingProjectId] = useState<string | null>(null);

  useEffect(() => {
    if (!userId) return;

    const q = query(
      collection(firestoreClient, "users", userId, "projects"),
      orderBy("createdAt", "desc")
    );

    const unsub = onSnapshot(
      q,
      (snap) => {
        const items: ProjectRow[] = snap.docs.map((d) => {
          const raw = d.data() as ProjectDoc;
          const data = isRecord(raw) ? raw : {};

          const createdAt = toDate(data.createdAt) ?? new Date();
          const updatedAt = toDate(data.updatedAt);
          const name = typeof data.name === "string" && data.name.trim() ? data.name.trim() : "Projekt";
          const archived = data.archived === true;

          return { id: d.id, name, createdAt, updatedAt, archived };
        });

        setProjects(items);
        setLoading(false);
      },
      (err) => {
        console.error("Failed to load projects:", err);
        toast.error("Projekte", { description: "Projekte konnten nicht geladen werden." });
        setProjects([]);
        setLoading(false);
      }
    );

    return () => {
      unsub();
    };
  }, [userId]);

  const activeProjects = useMemo(
    () => projects.filter((p) => p.archived !== true),
    [projects]
  );
  const archivedProjects = useMemo(
    () => projects.filter((p) => p.archived === true),
    [projects]
  );

  const renameValidationError = useMemo(() => {
    if (!renameDialogOpen) return null;
    if (!renameTarget) return null;

    const desired = normalizeName(renameValue);
    if (!desired) return "Projektname darf nicht leer sein.";

    const desiredNorm = desired.toLowerCase();
    const hasDuplicate = projects.some((p) => p.id !== renameTarget.id && normalizeName(p.name).toLowerCase() === desiredNorm);
    if (hasDuplicate) return "Ein Projekt mit diesem Namen existiert bereits (auch im Archiv).";

    return null;
  }, [projects, renameDialogOpen, renameTarget, renameValue]);

  const openRename = (p: ProjectRow) => {
    setRenameTarget(p);
    setRenameValue(p.name);
    setRenameDialogOpen(true);
  };

  const handleRenameSave = async () => {
    if (renameSaving) return;
    if (!renameTarget) return;

    const desired = normalizeName(renameValue);
    if (!desired || renameValidationError) return;

    setRenameSaving(true);
    try {
      const result = await renameProject(renameTarget.id, desired);
      if (!result.success) {
        throw new Error(result.error || "Projekt konnte nicht umbenannt werden.");
      }

      setRenameDialogOpen(false);
      toast.success("Projekt umbenannt");
    } catch (error) {
      console.error("Rename project error:", error);
      toast.error("Projekt umbenennen fehlgeschlagen", {
        description: error instanceof Error ? error.message : "Bitte versuche es erneut.",
      });
    } finally {
      setRenameSaving(false);
    }
  };

  const handleRestore = async (projectId: string) => {
    try {
      const result = await unarchiveProject(projectId);
      if (!result.success) throw new Error(result.error || "Projekt konnte nicht wiederhergestellt werden.");
      toast.success("Projekt wiederhergestellt");
    } catch (error) {
      console.error("Unarchive project error:", error);
      toast.error("Projekt wiederherstellen fehlgeschlagen", {
        description: error instanceof Error ? error.message : "Bitte versuche es erneut.",
      });
    }
  };

  const openDelete = (projectId: string) => {
    setDeleteConfirmValue("");
    setDeleteOpenProjectId((prev) => (prev === projectId ? null : projectId));
  };

  const closeDelete = () => {
    setDeleteOpenProjectId(null);
    setDeleteConfirmValue("");
  };

  const handlePermanentDelete = async (project: ProjectRow) => {
    if (deleteLoadingProjectId) return;
    if (!deleteOpenProjectId || deleteOpenProjectId !== project.id) return;

    const typed = normalizeName(deleteConfirmValue);
    const expected = normalizeName(project.name);
    if (!typed || typed.toLowerCase() !== expected.toLowerCase()) return;

    setDeleteLoadingProjectId(project.id);
    try {
      const res = await fetch(`/api/projects/${encodeURIComponent(project.id)}`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmName: typed }),
        cache: "no-store",
      });

      const data = (await res.json().catch(() => ({}))) as { status?: string; error?: string };
      if (!res.ok) {
        throw new Error(data?.error || "Projekt konnte nicht gelöscht werden.");
      }

      toast.success("Projekt gelöscht");
      closeDelete();
    } catch (error) {
      console.error("Permanent delete project error:", error);
      toast.error("Projekt löschen fehlgeschlagen", {
        description: error instanceof Error ? error.message : "Bitte versuche es erneut.",
      });
    } finally {
      setDeleteLoadingProjectId(null);
    }
  };

  return (
    <>
      {loading ? (
        <div className="space-y-3">
          {[...Array(3)].map((_, i) => (
            <Card key={i} className="py-0 gap-0">
              <CardContent className="px-6 py-4">
                <div className="h-4 w-56 bg-muted rounded" />
                <div className="h-3 w-40 bg-muted rounded mt-2" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <div className="space-y-10">
          <div>
            <h2 className="text-xl font-semibold text-foreground flex items-center gap-2">
              <FolderOpen className="h-5 w-5 text-muted-foreground" />
              Projektverwaltung
            </h2>
          </div>

          <section className="space-y-4">
            <div>
              <h3 className="text-base font-semibold text-foreground flex items-center gap-2">
                <FolderOpen className="h-4 w-4 text-muted-foreground" />
                Aktive Projekte
              </h3>
              <p className="text-sm text-muted-foreground">
                Deine aktuellen Projekte sind hier verfügbar
              </p>
            </div>

            {activeProjects.length === 0 ? (
              <div className="text-sm text-muted-foreground">Keine aktiven Projekte.</div>
            ) : (
              <div className="space-y-3">
                {activeProjects.map((p) => {
                  const updated = p.updatedAt ?? p.createdAt;
                  const deleteOpen = deleteOpenProjectId === p.id;
                  const typed = normalizeName(deleteConfirmValue);
                  const expected = normalizeName(p.name);
                  const matches = typed && typed.toLowerCase() === expected.toLowerCase();
                  const isDeleting = deleteLoadingProjectId === p.id;
                  const isDefault = p.id === "default";

                  return (
                    <Card key={p.id} className="py-0 gap-0">
                      <CardContent className="px-6 py-4">
                        <div className="flex items-start justify-between gap-4">
                          <div className="min-w-0">
                            <div className="font-medium text-foreground truncate">
                              {p.name}
                            </div>
                            <div className="text-sm text-muted-foreground mt-1">
                              Erstellt: {formatDate(p.createdAt)}{" "}
                              <span className="mx-2">·</span>
                              Zuletzt: {formatDate(updated)}
                            </div>
                          </div>

                          <div className="flex items-center gap-1 shrink-0">
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="h-9 w-9"
                              onClick={() => openRename(p)}
                              title="Umbenennen"
                            >
                              <Pencil className="h-4 w-4" />
                            </Button>

                            <Button
                              type="button"
                              variant={deleteOpen ? "outline" : "ghost"}
                              size={deleteOpen ? "sm" : "icon"}
                              className={
                                deleteOpen
                                  ? "h-9 text-red-600 border-red-200 hover:bg-red-50"
                                  : "h-9 w-9 text-red-600"
                              }
                              onClick={() => (isDefault ? null : openDelete(p.id))}
                              disabled={isDefault}
                              title={
                                isDefault
                                  ? "Standardprojekt kann nicht gelöscht werden"
                                  : "Löschen"
                              }
                            >
                              <Trash2 className={deleteOpen ? "h-4 w-4 mr-2" : "h-4 w-4"} />
                              {deleteOpen ? "Löschen" : null}
                            </Button>
                          </div>
                        </div>

                        {deleteOpen ? (
                          <div className="mt-4 rounded-lg border border-red-200 bg-red-50/70 p-4">
                            <div className="text-sm font-semibold text-red-700">
                              Möchtest du &quot;{p.name}&quot; wirklich löschen?
                            </div>
                            <p className="text-sm text-red-700/90 mt-1">
                              Diese Aktion kann nicht rückgängig gemacht werden. Alle Kapitel, Quellen und Texte werden unwiderruflich gelöscht.
                            </p>

                            <div className="mt-4 space-y-2">
                              <Label className="text-red-800">Gib den Projektnamen ein:</Label>
                              <Input
                                value={deleteConfirmValue}
                                onChange={(e) => setDeleteConfirmValue(e.target.value)}
                                placeholder={p.name}
                                disabled={isDeleting}
                              />
                            </div>

                            <div className="mt-4 flex items-center gap-2">
                              <Button
                                type="button"
                                variant="destructive"
                                onClick={() => handlePermanentDelete(p)}
                                disabled={!matches || isDeleting}
                              >
                                {isDeleting ? (
                                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                                ) : (
                                  <Trash2 className="h-4 w-4 mr-2" />
                                )}
                                Endgültig löschen
                              </Button>
                              <Button
                                type="button"
                                variant="outline"
                                onClick={closeDelete}
                                disabled={isDeleting}
                              >
                                Abbrechen
                              </Button>
                            </div>
                          </div>
                        ) : null}
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            )}
          </section>

          <section className="space-y-4">
            <div>
              <h3 className="text-base font-semibold text-foreground flex items-center gap-2">
                <Archive className="h-4 w-4 text-muted-foreground" />
                Archivierte Projekte
              </h3>
              <p className="text-sm text-muted-foreground">
                Diese Projekte sind archiviert und können wiederhergestellt werden
              </p>
            </div>

            {archivedProjects.length === 0 ? (
              <div className="text-sm text-muted-foreground">Keine archivierten Projekte.</div>
            ) : (
              <div className="space-y-3">
                {archivedProjects.map((p) => {
                  const updated = p.updatedAt ?? p.createdAt;
                  const deleteOpen = deleteOpenProjectId === p.id;
                  const typed = normalizeName(deleteConfirmValue);
                  const expected = normalizeName(p.name);
                  const matches = typed && typed.toLowerCase() === expected.toLowerCase();
                  const isDeleting = deleteLoadingProjectId === p.id;
                  const isDefault = p.id === "default";

                  return (
                    <Card key={p.id} className="py-0 gap-0 bg-muted/20">
                      <CardContent className="px-6 py-4">
                        <div className="flex items-start justify-between gap-4">
                          <div className="min-w-0">
                            <div className="font-medium text-foreground truncate">
                              {p.name}
                            </div>
                            <div className="text-sm text-muted-foreground mt-1">
                              Erstellt: {formatDate(p.createdAt)}{" "}
                              <span className="mx-2">·</span>
                              Zuletzt: {formatDate(updated)}
                            </div>
                          </div>

                          <div className="flex items-center gap-1 shrink-0">
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="h-9 w-9"
                              onClick={() => handleRestore(p.id)}
                              title="Wiederherstellen"
                            >
                              <RotateCcw className="h-4 w-4" />
                            </Button>

                            <Button
                              type="button"
                              variant={deleteOpen ? "outline" : "ghost"}
                              size={deleteOpen ? "sm" : "icon"}
                              className={
                                deleteOpen
                                  ? "h-9 text-red-600 border-red-200 hover:bg-red-50"
                                  : "h-9 w-9 text-red-600"
                              }
                              onClick={() => (isDefault ? null : openDelete(p.id))}
                              disabled={isDefault}
                              title={
                                isDefault
                                  ? "Standardprojekt kann nicht gelöscht werden"
                                  : "Löschen"
                              }
                            >
                              <Trash2 className={deleteOpen ? "h-4 w-4 mr-2" : "h-4 w-4"} />
                              {deleteOpen ? "Löschen" : null}
                            </Button>
                          </div>
                        </div>

                        {deleteOpen ? (
                          <div className="mt-4 rounded-lg border border-red-200 bg-red-50/70 p-4">
                            <div className="text-sm font-semibold text-red-700">
                              Möchtest du &quot;{p.name}&quot; wirklich löschen?
                            </div>
                            <p className="text-sm text-red-700/90 mt-1">
                              Diese Aktion kann nicht rückgängig gemacht werden. Alle Kapitel, Quellen und Texte werden unwiderruflich gelöscht.
                            </p>

                            <div className="mt-4 space-y-2">
                              <Label className="text-red-800">Gib den Projektnamen ein:</Label>
                              <Input
                                value={deleteConfirmValue}
                                onChange={(e) => setDeleteConfirmValue(e.target.value)}
                                placeholder={p.name}
                                disabled={isDeleting}
                              />
                            </div>

                            <div className="mt-4 flex items-center gap-2">
                              <Button
                                type="button"
                                variant="destructive"
                                onClick={() => handlePermanentDelete(p)}
                                disabled={!matches || isDeleting}
                              >
                                {isDeleting ? (
                                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                                ) : (
                                  <Trash2 className="h-4 w-4 mr-2" />
                                )}
                                Endgültig löschen
                              </Button>
                              <Button
                                type="button"
                                variant="outline"
                                onClick={closeDelete}
                                disabled={isDeleting}
                              >
                                Abbrechen
                              </Button>
                            </div>
                          </div>
                        ) : null}
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            )}
          </section>
        </div>
      )}

      <Dialog
        open={renameDialogOpen}
        onOpenChange={(open) => {
          setRenameDialogOpen(open);
          if (!open) {
            setRenameTarget(null);
            setRenameValue("");
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Projekt umbenennen</DialogTitle>
            <DialogDescription>Gib einen neuen Namen für dein Projekt ein.</DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            <Label htmlFor="rename-projekt-name">Name</Label>
            <Input
              id="rename-projekt-name"
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              placeholder="z.B. Masterarbeit: Digitalisierung im Mittelstand"
              maxLength={200}
              disabled={renameSaving}
            />
            {renameValidationError ? (
              <p className="text-xs text-destructive">{renameValidationError}</p>
            ) : null}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setRenameDialogOpen(false)} disabled={renameSaving}>
              Abbrechen
            </Button>
            <Button onClick={handleRenameSave} disabled={renameSaving || Boolean(renameValidationError)}>
              {renameSaving ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
              Speichern
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
