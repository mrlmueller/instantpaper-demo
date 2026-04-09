"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Search,
  Trash2,
  ChevronDown,
  ChevronUp,
  ArrowUpDown,
  FolderPlus,
  Eye,
  Pencil,
  ArrowLeft,
  Check,
  Loader2,
  Plus,
  ImageIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import type { Quelle } from "@/app/types/ui";
import type { Kapitel as FirebaseKapitel } from "@/app/actions/kapitels";
import { transformQuelleToUI } from "@/app/lib/transformers/ui-data";
import { useAuth } from "@/app/components/providers/AuthProvider";
import {
  createQuelle,
  updateQuelleColor,
  updateQuelleFull,
  bulkAssignQuellen,
  deleteQuelle,
  getQuelleContent,
  type ImageMetadata,
} from "@/app/actions/quellen";
import {
  QUELLE_COLORS,
  colorMap,
  colorLabels,
  type QuelleColor,
} from "@/app/lib/quellen/fieldConfig";
import { QuelleViewerModal } from "@/app/components/dashboard/QuelleViewerModal";
import { AddQuelleDialog } from "@/app/components/quellen/AddQuelleDialog";
import { EditQuelleDialog } from "@/app/components/quellen/EditQuelleDialog";

interface QuellenManagerProps {
  initialQuellen: any[];
  initialKapitels: FirebaseKapitel[];
  projektId: string;
  isLoading?: boolean;
}

type SortField = "name" | "typ" | "jahr" | "color";
type SortDirection = "asc" | "desc";

function compareKapitelNummer(a: string, b: string) {
  const partsA = a.split(".").map(Number);
  const partsB = b.split(".").map(Number);
  for (let i = 0; i < Math.max(partsA.length, partsB.length); i++) {
    const numA = partsA[i] || 0;
    const numB = partsB[i] || 0;
    if (numA !== numB) return numA - numB;
  }
  return 0;
}

const typLabels: Record<string, string> = {
  Book: "Buch",
  Article: "Artikel",
  Website: "Website",
  Thesis: "Thesis",
  Report: "Report",
};

export function QuellenManager({
  initialQuellen,
  initialKapitels,
  projektId,
  isLoading = false,
}: QuellenManagerProps) {
  const router = useRouter();
  const { user } = useAuth();
  const [quellen, setQuellen] = useState<Quelle[]>(
    initialQuellen.map((q) => transformQuelleToUI(q, projektId))
  );
  const [kapitels, setKapitels] = useState(initialKapitels);

  const [searchQuery, setSearchQuery] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [sortField, setSortField] = useState<SortField>("name");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [filterTyp, setFilterTyp] = useState<string | "all">("all");
  const [filterColor, setFilterColor] = useState<QuelleColor | "all" | null>(
    "all"
  );
  const [assignDialogOpen, setAssignDialogOpen] = useState(false);
  const [selectedKapitelIds, setSelectedKapitelIds] = useState<Set<string>>(
    new Set()
  );
  const [assigningQuelleId, setAssigningQuelleId] = useState<string | null>(
    null
  );
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [viewingQuelle, setViewingQuelle] = useState<Quelle | null>(null);
  const [viewingQuelleLoading, setViewingQuelleLoading] = useState(false);
  const [backLoading, setBackLoading] = useState(false);
  const [isEditDialogOpen, setIsEditDialogOpen] = useState(false);
  const [editingQuelleId, setEditingQuelleId] = useState<string | null>(null);
  const [isUpdatingQuelle, setIsUpdatingQuelle] = useState(false);

  const handleViewQuelle = async (quelle: Quelle) => {
    setViewingQuelleLoading(true);
    setViewingQuelle({ ...quelle, text: "" });
    try {
      const content = await getQuelleContent(quelle.id);
      if (content?.text != null) {
        setViewingQuelle((prev) => (prev?.id === quelle.id ? { ...prev, text: content.text } : prev));
      }
    } finally {
      setViewingQuelleLoading(false);
    }
  };

  // New Quelle dialog state
  const [isAddDialogOpen, setIsAddDialogOpen] = useState(false);
  const [isAddingQuelle, setIsAddingQuelle] = useState(false);

  const filteredQuellen = useMemo(() => {
    let result = quellen.filter((q) =>
      q.name.toLowerCase().includes(searchQuery.toLowerCase())
    );

    if (filterTyp !== "all") {
      result = result.filter((q) => q.typ === filterTyp);
    }

    if (filterColor !== "all") {
      result = result.filter((q) => q.color === filterColor);
    }

    result.sort((a, b) => {
      // First, group by color (colors first, then no-color)
      const colorOrder = [
        "blue",
        "green",
        "teal",
        "lavender",
        "cream",
        "peach",
        "rose",
      ];
      const aColorIndex = a.color ? colorOrder.indexOf(a.color) : 999;
      const bColorIndex = b.color ? colorOrder.indexOf(b.color) : 999;

      if (aColorIndex !== bColorIndex) {
        return aColorIndex - bColorIndex;
      }

      // Then sort within color group by the selected field
      let comparison = 0;
      switch (sortField) {
        case "name":
          comparison = a.name.localeCompare(b.name);
          break;
        case "typ":
          comparison = (a.typ || "").localeCompare(b.typ || "");
          break;
        case "jahr":
          comparison = (a.jahr || 0) - (b.jahr || 0);
          break;
        case "color":
          // Already grouped by color above
          comparison = a.name.localeCompare(b.name);
          break;
      }
      return sortDirection === "asc" ? comparison : -comparison;
    });

    return result;
  }, [quellen, searchQuery, filterTyp, filterColor, sortField, sortDirection]);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortDirection("asc");
    }
  };

  const handleSelectAll = () => {
    if (selectedIds.size === filteredQuellen.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredQuellen.map((q) => q.id)));
    }
  };

  const handleSelectOne = (id: string) => {
    const newSelected = new Set(selectedIds);
    if (newSelected.has(id)) {
      newSelected.delete(id);
    } else {
      newSelected.add(id);
    }
    setSelectedIds(newSelected);
  };

  const openAssignDialog = () => {
    // Clear any single-Quelle assignment state
    setAssigningQuelleId(null);
    // If exactly one Quelle is selected, pre-select Kapitels that already have it
    if (selectedIds.size === 1) {
      const quelleId = Array.from(selectedIds)[0];
      const linkedKapitels = kapitels.filter((k) =>
        (k.quelleIds ?? []).includes(quelleId)
      );
      setSelectedKapitelIds(new Set(linkedKapitels.map((k) => k.id)));
    } else {
      setSelectedKapitelIds(new Set());
    }
    setAssignDialogOpen(true);
  };

  const openAssignDialogForQuelle = (quelleId: string) => {
    // Don't modify selectedIds - just track which Quelle we're assigning
    setAssigningQuelleId(quelleId);
    // Pre-select Kapitels that already have this Quelle
    const linkedKapitels = kapitels.filter((k) =>
      (k.quelleIds ?? []).includes(quelleId)
    );
    setSelectedKapitelIds(new Set(linkedKapitels.map((k) => k.id)));
    setAssignDialogOpen(true);
  };

  const handleBack = () => {
    if (backLoading) return;
    setBackLoading(true);
    try {
      router.push("/dashboard");
    } catch {
      setBackLoading(false);
    }
  };

  const handleAssign = async () => {
    // Use assigningQuelleId if set (single Quelle from Kapitel column), otherwise use selectedIds
    const quelleIds = assigningQuelleId
      ? [assigningQuelleId]
      : Array.from(selectedIds);
    const count = quelleIds.length;
    const kapitelIds = Array.from(selectedKapitelIds);
    const kapitelCount = kapitelIds.length;
    const isSingleQuelle = quelleIds.length === 1;

    const previousKapitels = kapitels;

    // Optimistic update: update Kapitel->Quelle links locally right away.
    setKapitels((prev) => {
      const selectedKapitelIdSet = new Set(kapitelIds);
      const quelleIdSet = new Set(quelleIds);

      return prev.map((kapitel) => {
        const existingQuelleIds = kapitel.quelleIds ?? [];

        if (!isSingleQuelle) {
          if (!selectedKapitelIdSet.has(kapitel.id)) return kapitel;
          const updatedQuelleIds = Array.from(
            new Set([...existingQuelleIds, ...quelleIds])
          );
          if (updatedQuelleIds.length === existingQuelleIds.length) return kapitel;
          return { ...kapitel, quelleIds: updatedQuelleIds };
        }

        const withoutTargetQuellen = existingQuelleIds.filter(
          (id) => !quelleIdSet.has(id)
        );
        const updatedQuelleIds = selectedKapitelIdSet.has(kapitel.id)
          ? Array.from(new Set([...withoutTargetQuellen, ...quelleIds]))
          : withoutTargetQuellen;

        if (
          updatedQuelleIds.length === existingQuelleIds.length &&
          updatedQuelleIds.every((id, i) => id === existingQuelleIds[i])
        ) {
          return kapitel;
        }
        return { ...kapitel, quelleIds: updatedQuelleIds };
      });
    });

    setAssignDialogOpen(false);
    setSelectedKapitelIds(new Set());
    setAssigningQuelleId(null);
    setSelectedIds(new Set());

    try {
      const result = await bulkAssignQuellen(
        quelleIds,
        kapitelIds,
        projektId,
        undefined,
        isSingleQuelle
      );
      if (result?.success === false) {
        throw new Error(result.error || "Unknown error");
      }

      if (kapitelCount === 0 && isSingleQuelle) {
        toast.success("Kapitel-Zuweisung entfernt");
      } else {
        toast.success(`${count} Quellen zu ${kapitelCount} Kapiteln zugewiesen`);
      }
    } catch (error) {
      setKapitels(previousKapitels);
      toast.error("Fehler beim Zuweisen der Quellen");
    }
  };

  const handleColorChange = async (
    quelleId: string,
    color: QuelleColor | null
  ) => {
    // Optimistic update - update UI immediately
    setQuellen((prev) =>
      prev.map((q) => (q.id === quelleId ? { ...q, color } : q))
    );

    try {
      await updateQuelleColor(quelleId, color);
    } catch (error) {
      // Revert on error by refreshing
      router.refresh();
    }
  };

  const handleDelete = async () => {
    const selectedQuelleIds = Array.from(selectedIds);
    try {
      // Delete all selected quellen
      await Promise.all(selectedQuelleIds.map((id) => deleteQuelle(id)));
      setQuellen((prev) => prev.filter((q) => !selectedIds.has(q.id)));
      setSelectedIds(new Set());
      setDeleteConfirmOpen(false);
      toast.success(`${selectedQuelleIds.length} Quelle(n) gelöscht`);
      router.refresh();
    } catch (error) {
      toast.error("Fehler beim Löschen der Quellen");
    }
  };

  const handleAddQuelle = async (
    name: string,
    text: string,
    imageFiles: File[] = [],
    advancedFields?: Record<string, any>
  ): Promise<boolean> => {
    if (isAddingQuelle) return false;
    if (!user) {
      toast.error("Nicht eingeloggt");
      return false;
    }

    setIsAddingQuelle(true);

    const loadingToast = toast.loading("Quelle wird hinzugefügt...");
    const uploadingToast =
      imageFiles.length > 0
        ? toast.loading(`Lade ${imageFiles.length} Bild(er) hoch...`)
        : undefined;

    let imageMetadata: ImageMetadata[] = [];
    let success = false;

    try {
      if (imageFiles.length > 0) {
        const { uploadImagesToStorage } = await import(
          "@/app/lib/firebase/storage"
        );
        imageMetadata = await uploadImagesToStorage(user.uid, imageFiles);
      }

      const result = await createQuelle(
        name,
        text,
        projektId,
        imageMetadata,
        advancedFields
      );

      if (uploadingToast) toast.dismiss(uploadingToast);

      if (result.success && result.id) {
        success = true;
        toast.success("Quelle hinzugefügt", { id: loadingToast });

        const optimisticQuelle: Quelle = {
          id: result.id,
          name,
          text,
          projektId,
          createdAt: new Date(),
          images: result.imageUrls || [],
          ...(advancedFields || {}),
        };

        setQuellen((prev) => [optimisticQuelle, ...prev]);
        router.refresh();
      } else {
        toast.error("Fehler", { description: result.error, id: loadingToast });

        if (imageMetadata.length > 0) {
          const { deleteImagesFromStorage } = await import(
            "@/app/lib/firebase/storage"
          );
          await deleteImagesFromStorage(imageMetadata.map((img) => img.path));
        }
      }
    } catch (error) {
      if (uploadingToast) toast.dismiss(uploadingToast);

      toast.error("Upload fehlgeschlagen", {
        description:
          error instanceof Error ? error.message : "Unbekannter Fehler",
        id: loadingToast,
      });

      if (imageMetadata.length > 0) {
        const { deleteImagesFromStorage } = await import(
          "@/app/lib/firebase/storage"
        );
        await deleteImagesFromStorage(imageMetadata.map((img) => img.path));
      }
    } finally {
      setIsAddingQuelle(false);
    }

    return success;
  };

  const openEditDialogForQuelle = (quelleId: string) => {
    setEditingQuelleId(quelleId);
    setIsEditDialogOpen(true);
  };

  const handleSaveEditedQuelle = async (payload: {
    quelleId: string;
    name: string;
    text: string;
    keptImages: ImageMetadata[];
    newImageFiles: File[];
    removedImagePaths: string[];
    advancedFields: {
      autor?: string | null;
      jahr?: number | null;
      typ?: Quelle["typ"] | null;
      url?: string | null;
      zugriffAm?: string | null;
      zitat?: string | null;
      zitatModus?: Quelle["zitatModus"] | null;
      color?: QuelleColor | null;
    };
  }): Promise<boolean> => {
    if (isUpdatingQuelle) return false;
    if (!user) {
      toast.error("Nicht eingeloggt");
      return false;
    }

    setIsUpdatingQuelle(true);
    const savingToast = toast.loading("Quelle wird aktualisiert...");
    const uploadingToast =
      payload.newImageFiles.length > 0
        ? toast.loading(`Lade ${payload.newImageFiles.length} Bild(er) hoch...`)
        : undefined;

    let uploadedImages: ImageMetadata[] = [];
    try {
      const { uploadImagesToStorage, deleteImagesFromStorage } = await import(
        "@/app/lib/firebase/storage"
      );

      if (payload.newImageFiles.length > 0) {
        uploadedImages = await uploadImagesToStorage(
          user.uid,
          payload.newImageFiles
        );
      }

      const finalImages = [...payload.keptImages, ...uploadedImages];

      const result = await updateQuelleFull(
        payload.quelleId,
        {
          title: payload.name,
          content: payload.text,
          images: finalImages,
          advancedFields: payload.advancedFields,
        }
      );

      if (result?.success === false) {
        throw new Error(result.error || "Unknown error");
      }

      if (uploadingToast) toast.dismiss(uploadingToast);
      toast.success("Quelle aktualisiert", { id: savingToast });

      setQuellen((prev) =>
        prev.map((q) => {
          if (q.id !== payload.quelleId) return q;
          const next: Quelle = {
            ...q,
            name: payload.name,
            images: finalImages.length > 0 ? finalImages.map((img) => img.url) : undefined,
          };

          const af = payload.advancedFields;
          const hasOwn = (key: string) =>
            Object.prototype.hasOwnProperty.call(af, key);

          if (hasOwn("autor")) next.autor = af.autor ?? undefined;
          if (hasOwn("jahr")) next.jahr = af.jahr ?? undefined;
          if (hasOwn("typ")) next.typ = af.typ ?? undefined;
          if (hasOwn("url")) next.url = af.url ?? undefined;
          if (hasOwn("zugriffAm")) next.zugriffAm = af.zugriffAm ?? undefined;
          if (hasOwn("zitat")) next.zitat = af.zitat ?? undefined;
          if (hasOwn("zitatModus")) next.zitatModus = af.zitatModus ?? undefined;
          if (hasOwn("color")) next.color = af.color ?? null;

          return next;
        })
      );

      router.refresh();

      if (payload.removedImagePaths.length > 0) {
        deleteImagesFromStorage(payload.removedImagePaths).catch((err) => {
          console.error("Failed to delete removed images:", err);
        });
      }

      return true;
    } catch (error) {
      if (uploadingToast) toast.dismiss(uploadingToast);
      toast.error("Fehler beim Speichern", {
        description: error instanceof Error ? error.message : "Unbekannter Fehler",
        id: savingToast,
      });

      if (uploadedImages.length > 0) {
        const { deleteImagesFromStorage } = await import(
          "@/app/lib/firebase/storage"
        );
        await deleteImagesFromStorage(uploadedImages.map((img) => img.path));
      }

      return false;
    } finally {
      setIsUpdatingQuelle(false);
    }
  };

  const getLinkedKapiteln = (quelleId: string) => {
    return kapitels.filter((k) => (k.quelleIds ?? []).includes(quelleId));
  };

  useEffect(() => {
    setKapitels(initialKapitels);
  }, [initialKapitels]);

  useEffect(() => {
    setQuellen(initialQuellen.map((q) => transformQuelleToUI(q, projektId)));
  }, [initialQuellen, projektId]);

  const sortedKapiteln = useMemo(() => {
    return [...kapitels].sort((a, b) => {
      if (!a.nummer || !b.nummer) return 0;
      const partsA = a.nummer.split(".").map(Number);
      const partsB = b.nummer.split(".").map(Number);
      for (let i = 0; i < Math.max(partsA.length, partsB.length); i++) {
        const numA = partsA[i] || 0;
        const numB = partsB[i] || 0;
        if (numA !== numB) return numA - numB;
      }
      return 0;
    });
  }, [kapitels]);

  const SortButton = ({
    field,
    children,
  }: {
    field: SortField;
    children: React.ReactNode;
  }) => (
    <Button
      variant="ghost"
      size="sm"
      className="h-8 px-2 -ml-2 font-medium hover:bg-muted/50"
      onClick={() => handleSort(field)}
    >
      {children}
      {sortField === field ? (
        sortDirection === "asc" ? (
          <ChevronUp className="ml-1 h-4 w-4" />
        ) : (
          <ChevronDown className="ml-1 h-4 w-4" />
        )
      ) : (
        <ArrowUpDown className="ml-1 h-4 w-4 opacity-30" />
      )}
    </Button>
  );

  if (isLoading) {
    return (
      <div className="h-full min-h-0 bg-background flex flex-col">
        <div className="shrink-0 border-b border-border px-6 py-4 flex items-center gap-4">
          <Skeleton className="h-9 w-9" />
          <div>
            <Skeleton className="h-6 w-40 mb-1" />
            <Skeleton className="h-4 w-24" />
          </div>
        </div>
        <div className="shrink-0 border-b border-border px-6 py-3 flex items-center gap-4 flex-wrap">
          <Skeleton className="h-9 w-64" />
          <Skeleton className="h-9 w-32" />
          <Skeleton className="h-9 w-32" />
          <div className="flex-1" />
          <Skeleton className="h-9 w-40" />
        </div>
        <div className="min-h-0 flex-1 overflow-auto px-6 py-4">
          <Card className="p-4">
            <div className="space-y-3">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="h-full min-h-0 overflow-hidden bg-background flex flex-col">
        {/* Header */}
        <div className="shrink-0 border-b border-border px-6 py-4 flex items-center gap-4">
          <Button
            variant="ghost"
            size="icon"
            onClick={handleBack}
            disabled={backLoading}
            aria-label="Zurück zum Dashboard"
          >
            {backLoading ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : (
              <ArrowLeft className="h-5 w-5" />
            )}
          </Button>
          <div>
            <h1 className="text-xl font-semibold">Quellen-Manager</h1>
            <p className="text-sm text-muted-foreground">
              {quellen.length} Quellen
            </p>
          </div>
        </div>

        {/* Toolbar */}
        <div className="shrink-0 border-b border-border px-6 py-3 flex items-center gap-4 flex-wrap">
          <div className="relative flex-1 min-w-[200px] max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Quellen durchsuchen..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9"
            />
          </div>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                Typ:{" "}
                {filterTyp === "all"
                  ? "Alle"
                  : typLabels[filterTyp] || filterTyp}
                <ChevronDown className="ml-2 h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuItem onClick={() => setFilterTyp("all")}>
                Alle
              </DropdownMenuItem>
              {Object.entries(typLabels).map(([key, label]) => (
                <DropdownMenuItem key={key} onClick={() => setFilterTyp(key)}>
                  {label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                <span
                  className="w-4 h-4 rounded mr-2"
                  style={{
                    backgroundColor:
                      filterColor && filterColor !== "all"
                        ? colorMap[filterColor]
                        : "var(--muted)",
                    border:
                      filterColor === "all" || !filterColor
                        ? "1px solid var(--border)"
                        : undefined,
                  }}
                />
                Farbe
                <ChevronDown className="ml-2 h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuItem onClick={() => setFilterColor("all")}>
                Alle Farben
              </DropdownMenuItem>
              {QUELLE_COLORS.map((color) => (
                <DropdownMenuItem
                  key={color}
                  onClick={() => setFilterColor(color)}
                >
                  <span
                    className="w-4 h-4 rounded mr-2"
                    style={{ backgroundColor: colorMap[color] }}
                  />
                  {colorLabels[color]}
                </DropdownMenuItem>
              ))}
              <DropdownMenuItem onClick={() => setFilterColor(null)}>
                <span className="w-4 h-4 rounded bg-background border mr-2" />
                Keine Farbe
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          <div className="flex-1" />

          <div className="flex items-center gap-2">
            {selectedIds.size > 0 && (
              <>
                <Badge variant="secondary" className="px-3 py-1">
                  {selectedIds.size} ausgewählt
                </Badge>
                {selectedIds.size === 1 && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={openAssignDialog}
                  >
                    <FolderPlus className="h-4 w-4 mr-2" />
                    Zu Kapitel
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => setDeleteConfirmOpen(true)}
                >
                  <Trash2 className="h-4 w-4 mr-2" />
                  Löschen
                </Button>
              </>
            )}

            <Button size="sm" onClick={() => setIsAddDialogOpen(true)}>
              <Plus className="h-4 w-4 mr-2" />
              Quelle hinzufügen
            </Button>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-auto px-6 py-4">
          <Card>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">
                    <Checkbox
                      checked={
                        filteredQuellen.length > 0 &&
                        selectedIds.size === filteredQuellen.length
                      }
                      onCheckedChange={handleSelectAll}
                    />
                  </TableHead>
                  <TableHead className="w-12">Farbe</TableHead>
                  <TableHead>
                    <SortButton field="name">Name</SortButton>
                  </TableHead>
                  <TableHead className="w-28">
                    <SortButton field="typ">Typ</SortButton>
                  </TableHead>
                  <TableHead className="w-20">Bilder</TableHead>
                  <TableHead className="w-20">
                    <SortButton field="jahr">Jahr</SortButton>
                  </TableHead>
                  <TableHead className="w-40">Kapitel</TableHead>
                  <TableHead className="w-20 text-right">Aktionen</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredQuellen.map((quelle) => {
                  const linkedKapiteln = [...getLinkedKapiteln(quelle.id)].sort(
                    (a, b) => compareKapitelNummer(a.nummer || "", b.nummer || "")
                  );
                  return (
                    <TableRow key={quelle.id} className="group">
                      <TableCell>
                        <Checkbox
                          checked={selectedIds.has(quelle.id)}
                          onCheckedChange={() => handleSelectOne(quelle.id)}
                        />
                      </TableCell>
                      <TableCell>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <button
                              className="w-6 h-6 rounded border-2 transition-all hover:scale-110"
                              style={{
                                backgroundColor: quelle.color
                                  ? colorMap[quelle.color]
                                  : "var(--background)",
                                borderColor: quelle.color
                                  ? colorMap[quelle.color]
                                  : "var(--border)",
                              }}
                            />
                          </DropdownMenuTrigger>
                          <DropdownMenuContent>
                            {QUELLE_COLORS.map((color) => (
                              <DropdownMenuItem
                                key={color}
                                onClick={() =>
                                  handleColorChange(quelle.id, color)
                                }
                                className="flex items-center gap-2"
                              >
                                <span
                                  className="w-4 h-4 rounded"
                                  style={{ backgroundColor: colorMap[color] }}
                                />
                                {colorLabels[color]}
                                {quelle.color === color && (
                                  <Check className="h-3 w-3 ml-auto" />
                                )}
                              </DropdownMenuItem>
                            ))}
                            <DropdownMenuItem
                              onClick={() => handleColorChange(quelle.id, null)}
                              className="flex items-center gap-2"
                            >
                              <span className="w-4 h-4 rounded bg-background border" />
                              Keine Farbe
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </TableCell>
                      <TableCell
                        className="cursor-pointer"
                        onClick={() => handleSelectOne(quelle.id)}
                      >
                        <div className="font-medium truncate max-w-[300px]">
                          {quelle.name}
                        </div>
                        {quelle.autor && (
                          <div className="text-xs text-muted-foreground">
                            {quelle.autor}
                          </div>
                        )}
                      </TableCell>
                      <TableCell className="text-muted-foreground text-sm">
                        {quelle.typ ? typLabels[quelle.typ] || quelle.typ : "-"}
                      </TableCell>
                      <TableCell className="text-muted-foreground text-sm">
                        {quelle.images && quelle.images.length > 0 ? (
                          <div className="flex items-center gap-1">
                            <ImageIcon className="h-4 w-4 text-muted-foreground" />
                            {quelle.images.length > 1 && (
                              <span className="text-xs font-medium text-muted-foreground">
                                +{quelle.images.length - 1}
                              </span>
                            )}
                          </div>
                        ) : (
                          "-"
                        )}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {quelle.jahr || "-"}
                      </TableCell>
                      <TableCell>
                        {linkedKapiteln.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {linkedKapiteln.slice(0, 2).map((k) => (
                              <Badge
                                key={k.id}
                                variant="outline"
                                className="text-xs px-1.5 py-0 cursor-pointer hover:bg-muted transition-colors"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  openAssignDialogForQuelle(quelle.id);
                                }}
                              >
                                {k.nummer}
                              </Badge>
                            ))}
                            {linkedKapiteln.length > 2 && (
                              <span
                                className="text-xs text-muted-foreground cursor-pointer hover:underline"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  openAssignDialogForQuelle(quelle.id);
                                }}
                              >
                                +{linkedKapiteln.length - 2}
                              </span>
                            )}
                          </div>
                        ) : (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2 text-xs text-muted-foreground hover:text-primary"
                            onClick={(e) => {
                              e.stopPropagation();
                              openAssignDialogForQuelle(quelle.id);
                            }}
                          >
                            <Plus className="h-3 w-3 mr-1" />
                            Zuweisen
                          </Button>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            onClick={() => handleViewQuelle(quelle)}
                            aria-label="Quelle ansehen"
                          >
                            <Eye className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            onClick={() => openEditDialogForQuelle(quelle.id)}
                            aria-label="Quelle bearbeiten"
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
                {filteredQuellen.length === 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={8}
                      className="h-24 text-center text-muted-foreground"
                    >
                      Keine Quellen gefunden
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </Card>
        </div>
      </div>

      <AddQuelleDialog
        open={isAddDialogOpen}
        onOpenChange={setIsAddDialogOpen}
        onAddQuelle={handleAddQuelle}
        isAddingQuelle={isAddingQuelle}
      />

      <EditQuelleDialog
        open={isEditDialogOpen}
        quelleId={editingQuelleId}
        onOpenChange={(open) => {
          setIsEditDialogOpen(open);
          if (!open) setEditingQuelleId(null);
        }}
        onSave={handleSaveEditedQuelle}
      />

      {/* Assign Dialog */}
      <Dialog
        open={assignDialogOpen}
        onOpenChange={(open) => {
          setAssignDialogOpen(open);
          if (!open) {
            setAssigningQuelleId(null);
            setSelectedKapitelIds(new Set());
          }
        }}
      >
      <DialogContent className="max-w-md !max-h-[70vh] flex flex-col">
          <DialogHeader>
            <DialogTitle>Zu Kapiteln zuweisen</DialogTitle>
          </DialogHeader>
          <div className="py-4 flex flex-col flex-1 min-h-0 overflow-hidden">
            <p className="text-sm text-muted-foreground mb-4">
              {(assigningQuelleId ? 1 : selectedIds.size)} Quelle(n) zu folgenden
              Kapiteln zuweisen:
            </p>
            <div className="space-y-2 flex-1 min-h-0 overflow-y-auto">
              {sortedKapiteln.map((kapitel) => {
                const depth = kapitel.nummer
                  ? kapitel.nummer.split(".").length - 1
                  : 0;
                return (
                  <div
                    key={kapitel.id}
                    className={cn(
                      "flex items-center gap-3 p-2 rounded hover:bg-muted/50 cursor-pointer",
                      selectedKapitelIds.has(kapitel.id) && "bg-muted"
                    )}
                    style={{ paddingLeft: `${8 + depth * 16}px` }}
                    onClick={() => {
                      const newSet = new Set(selectedKapitelIds);
                      if (newSet.has(kapitel.id)) {
                        newSet.delete(kapitel.id);
                      } else {
                        newSet.add(kapitel.id);
                      }
                      setSelectedKapitelIds(newSet);
                    }}
                  >
                    <Checkbox checked={selectedKapitelIds.has(kapitel.id)} />
                    <span className="text-sm font-medium">
                      {kapitel.nummer || ""}
                    </span>
                    <span className="text-sm text-muted-foreground truncate">
                      {kapitel.title}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setAssignDialogOpen(false)}
            >
              Abbrechen
            </Button>
            <Button
              onClick={handleAssign}
              disabled={
                selectedKapitelIds.size === 0 &&
                !(assigningQuelleId || selectedIds.size === 1)
              }
            >
              Zuweisen
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteConfirmOpen} onOpenChange={setDeleteConfirmOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>
              {selectedIds.size === 1
                ? "Quelle löschen"
                : `${selectedIds.size} Quellen löschen`}
            </DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <p className="text-sm text-muted-foreground">
              Möchten Sie{" "}
              {selectedIds.size === 1
                ? "diese Quelle"
                : `diese ${selectedIds.size} Quellen`}{" "}
              wirklich löschen? Diese Aktion kann nicht rückgängig gemacht
              werden.
            </p>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteConfirmOpen(false)}
            >
              Abbrechen
            </Button>
            <Button variant="destructive" onClick={handleDelete}>
              Löschen
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Quelle Viewer Modal */}
      <QuelleViewerModal
        quelle={viewingQuelle}
        loading={viewingQuelleLoading}
        open={viewingQuelle !== null}
        onOpenChange={(open) => !open && setViewingQuelle(null)}
      />
    </>
  );
}
