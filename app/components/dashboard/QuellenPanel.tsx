"use client";

import { useState, useRef, useEffect } from "react";
import {
  X,
  Plus,
  Eye,
  Trash2,
  CheckCircle2,
  Circle,
  Search,
  Palette,
  Settings,
  Check,
  ImageIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { useRouter } from "next/navigation";
import type { Quelle } from "@/app/types/ui";
import {
  colorMap,
  colorLabels,
  QUELLE_COLORS,
  QUELLE_TYPES,
  type QuelleColor,
} from "@/app/lib/quellen/fieldConfig";
import {
  computeQuelleZitatPreview,
  type QuelleZitatModus,
  toOneLine,
} from "@/app/lib/quellen/zitat";
import {
  getQuellenModeAdvanced,
  setQuellenModeAdvanced,
} from "@/app/lib/storage/preferences";
import { updateQuelleColor } from "@/app/actions/quellen";
import { fetchImageUrlAsFile } from "@/app/lib/images/imageUrlToFile";

interface QuellenPanelProps {
  quellen: Quelle[];
  assignedQuellenIds: string[];
  onClose: () => void;
  onAddQuelle: (
    name: string,
    text: string,
    imageFiles?: File[],
    advancedFields?: Record<string, any>
  ) => Promise<boolean>;
  onDeleteQuelle: (id: string, name: string) => void;
  onAssignQuelle: (id: string) => Promise<void>;
  onUnassignQuelle: (id: string) => Promise<void>;
  onViewQuelle: (quelle: Quelle) => void;
  isAddingQuelle: boolean;
  assigningQuelleIds: string[];
  unassigningQuelleIds: string[];
  deletingQuelleIds: string[];
}

const typLabels: Record<string, string> = {
  Book: "Buch",
  Article: "Artikel",
  Website: "Website",
  Thesis: "Thesis",
  Report: "Report",
};

export function QuellenPanel({
  quellen,
  assignedQuellenIds,
  onClose,
  onAddQuelle,
  onDeleteQuelle,
  onAssignQuelle,
  onUnassignQuelle,
  onViewQuelle,
  isAddingQuelle,
  assigningQuelleIds,
  unassigningQuelleIds,
  deletingQuelleIds,
}: QuellenPanelProps) {
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isAddDialogOpen, setIsAddDialogOpen] = useState(false);
  const [isUpdatingColor, setIsUpdatingColor] = useState(false);

  // Optimistic color updates - track local color changes
  const [colorUpdates, setColorUpdates] = useState<
    Map<string, QuelleColor | null>
  >(new Map());

  // Advanced mode state
  const [isAdvancedMode, setIsAdvancedMode] = useState(() =>
    getQuellenModeAdvanced()
  );
  const [advancedFieldValues, setAdvancedFieldValues] = useState<
    Record<string, any>
  >({});

  // New quelle form state
  const [newQuelleName, setNewQuelleName] = useState("");
  const [newQuelleText, setNewQuelleText] = useState("");
  const [newQuelleImages, setNewQuelleImages] = useState<File[]>([]);
  const [newQuelleColor, setNewQuelleColor] = useState<QuelleColor | null>(
    null
  );
  const [zitat, setZitat] = useState("");
  const [zitatModus, setZitatModus] = useState<QuelleZitatModus>("auto");

  // Image upload state
  const [imageUploadMode, setImageUploadMode] = useState<"upload" | "url">(
    "upload"
  );
  const [imageUrl, setImageUrl] = useState("");
  const [isAddingImageUrl, setIsAddingImageUrl] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Persist advanced mode preference
  useEffect(() => {
    setQuellenModeAdvanced(isAdvancedMode);
  }, [isAdvancedMode]);

  // Clear optimistic updates when props update (server data arrives)
  useEffect(() => {
    setColorUpdates((prev) => {
      const next = new Map(prev);
      // Remove updates that match the current server state
      quellen.forEach((q) => {
        const optimisticColor = prev.get(q.id);
        if (optimisticColor !== undefined && optimisticColor === q.color) {
          next.delete(q.id);
        }
      });
      return next;
    });
  }, [quellen]);

  // Apply optimistic color updates to quellen
  const quellenWithOptimisticColors = quellen.map((q) => {
    const optimisticColor = colorUpdates.get(q.id);
    return optimisticColor !== undefined ? { ...q, color: optimisticColor } : q;
  });

  // Filter and sort quellen
  const filteredQuellen = quellenWithOptimisticColors.filter(
    (q) =>
      q.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      q.text.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Sort: assigned first, then by color groups
  const sortedQuellen = [...filteredQuellen].sort((a, b) => {
    const aAssigned = assignedQuellenIds.includes(a.id);
    const bAssigned = assignedQuellenIds.includes(b.id);
    if (aAssigned !== bAssigned) return aAssigned ? -1 : 1;
    // Then by color
    const colorOrder = [
      "blue",
      "green",
      "teal",
      "lavender",
      "cream",
      "peach",
      "rose",
      null,
    ];
    const aColorIndex = colorOrder.indexOf(a.color || null);
    const bColorIndex = colorOrder.indexOf(b.color || null);
    return aColorIndex - bColorIndex;
  });

  // Separate assigned and unassigned
  const assignedQuellen = sortedQuellen.filter((q) =>
    assignedQuellenIds.includes(q.id)
  );
  const unassignedQuellen = sortedQuellen.filter(
    (q) => !assignedQuellenIds.includes(q.id)
  );

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const files = Array.from(e.dataTransfer.files).filter((file) =>
      file.type.startsWith("image/")
    );
    handleFiles(files);
  };

  const handleFiles = (files: File[]) => {
    const remainingSlots = 9 - newQuelleImages.length;
    const filesToProcess = files.slice(0, remainingSlots);
    setNewQuelleImages((prev) => [...prev, ...filesToProcess]);
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      handleFiles(Array.from(e.target.files));
    }
  };

  const removeImage = (index: number) => {
    setNewQuelleImages((prev) => prev.filter((_, i) => i !== index));
  };

  const handleAddImageUrl = async () => {
    const url = imageUrl.trim();
    if (!url || newQuelleImages.length >= 9 || isAddingImageUrl) return;

    setIsAddingImageUrl(true);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15_000);
    try {
      const file = await fetchImageUrlAsFile(url, { signal: controller.signal });
      setNewQuelleImages((prev) => [...prev, file].slice(0, 9));
      setImageUrl("");
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Bild konnte nicht geladen werden.";
      alert(message);
    } finally {
      clearTimeout(timer);
      setIsAddingImageUrl(false);
    }
  };

  const handleAddQuelle = async () => {
    if (newQuelleName && newQuelleText) {
      const normalizedZitat = toOneLine(zitat);
      const allAdvancedFields: Record<string, any> = {
        ...(isAdvancedMode ? advancedFieldValues : {}),
        ...(normalizedZitat ? { zitat: normalizedZitat } : {}),
        zitatModus,
        ...(newQuelleColor ? { color: newQuelleColor } : {}),
      };

      const success = await onAddQuelle(
        newQuelleName,
        newQuelleText,
        newQuelleImages.length > 0 ? newQuelleImages : undefined,
        allAdvancedFields
      );

      if (success) {
        setNewQuelleName("");
        setNewQuelleText("");
        setNewQuelleImages([]);
        setNewQuelleColor(null);
        setAdvancedFieldValues({});
        setImageUrl("");
        setZitat("");
        setZitatModus("auto");
        setIsAddDialogOpen(false);
      }
    }
  };

  const handleUpdateColor = async (
    quelleId: string,
    color: QuelleColor | null
  ) => {
    // Optimistic update - update local state immediately
    setColorUpdates((prev) => {
      const next = new Map(prev);
      next.set(quelleId, color);
      return next;
    });

    setIsUpdatingColor(true);
    try {
      await updateQuelleColor(quelleId, color);
      // Don't refresh immediately - keep the optimistic update
      // The next time the parent component refreshes, it will get the updated data
    } catch (error) {
      // Error - revert optimistic update
      setColorUpdates((prev) => {
        const next = new Map(prev);
        next.delete(quelleId);
        return next;
      });
    } finally {
      setIsUpdatingColor(false);
    }
  };

  const renderQuelleCard = (quelle: Quelle, isAssigned: boolean) => {
    const isSelected = selectedId === quelle.id;
    const cardColor = quelle.color ? colorMap[quelle.color] : null;

    return (
      <Card
        key={quelle.id}
        className={cn(
          "p-3 cursor-pointer transition-all relative overflow-hidden border",
          isAssigned
            ? "shadow-md border-border"
            : "shadow-none border-border/50 bg-muted/30"
        )}
        style={{
          borderColor: isSelected
            ? cardColor || "hsl(var(--primary))"
            : undefined,
          boxShadow: isSelected
            ? `0 0 0 2px ${cardColor || "hsl(var(--primary))"}`
            : isAssigned
            ? "0 2px 8px rgba(0,0,0,0.08)"
            : undefined,
        }}
        onMouseEnter={(e) => {
          if (!isSelected) {
            e.currentTarget.style.borderColor =
              cardColor || "hsl(var(--primary) / 0.5)";
          }
        }}
        onMouseLeave={(e) => {
          if (!isSelected) {
            e.currentTarget.style.borderColor = "";
          }
        }}
        onClick={() => setSelectedId(isSelected ? null : quelle.id)}
      >
        {/* Color bar at top */}
        {quelle.color && (
          <div
            className="absolute top-0 left-0 right-0 h-1.5"
            style={{ backgroundColor: cardColor || undefined }}
          />
        )}

        {/* Card content */}
        <div style={{ marginTop: quelle.color ? "6px" : "0" }}>
          <div className="flex items-center justify-between">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <p className="text-sm font-medium truncate">{quelle.name}</p>
                {quelle.images && quelle.images.length > 0 && (
                  <div className="flex items-center gap-0.5 shrink-0">
                    <ImageIcon className="h-3.5 w-3.5 text-muted-foreground" />
                    {quelle.images.length > 1 && (
                      <span className="text-[10px] text-muted-foreground font-medium">
                        +{quelle.images.length - 1}
                      </span>
                    )}
                  </div>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                {(
                  typeof quelle.wordCount === "number"
                    ? quelle.wordCount
                    : quelle.text.split(/\s+/).filter(Boolean).length
                ).toLocaleString("de-DE")}{" "}
                Wörter
                {quelle.typ && ` · ${typLabels[quelle.typ]}`}
                {quelle.jahr && ` · ${quelle.jahr}`}
              </p>
            </div>
            {isAssigned ? (
              <CheckCircle2 className="h-5 w-5 text-primary shrink-0 ml-2 fill-primary/20" />
            ) : (
              <Circle className="h-5 w-5 text-muted-foreground/30 shrink-0 ml-2" />
            )}
          </div>

          {/* Expanded content when selected */}
          {isSelected && (
            <div className="mt-2 pt-2 border-t border-border/50">
              {/* Color picker */}
              <div className="flex items-center gap-2 mb-2">
                <Popover>
                  <PopoverTrigger asChild>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 px-2"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <Palette className="h-4 w-4 text-muted-foreground shrink-0" />
                      <span className="text-xs ml-1.5">Farbe</span>
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent
                    className="w-auto p-2"
                    align="start"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div className="flex flex-wrap gap-1.5 max-w-[160px]">
                      <button
                        className={cn(
                          "w-6 h-6 rounded-full border-2 flex items-center justify-center",
                          !quelle.color
                            ? "border-primary"
                            : "border-border hover:border-muted-foreground"
                        )}
                        onClick={() => handleUpdateColor(quelle.id, null)}
                      >
                        <X className="h-3 w-3 text-muted-foreground" />
                      </button>
                      {QUELLE_COLORS.map((color) => (
                        <button
                          key={color}
                          className={cn(
                            "w-6 h-6 rounded-full border-2 flex items-center justify-center",
                            quelle.color === color
                              ? "border-primary"
                              : "border-transparent hover:border-muted-foreground"
                          )}
                          style={{ backgroundColor: colorMap[color] }}
                          onClick={() => handleUpdateColor(quelle.id, color)}
                        >
                          {quelle.color === color && (
                            <Check className="h-3.5 w-3.5 text-foreground/70" />
                          )}
                        </button>
                      ))}
                    </div>
                  </PopoverContent>
                </Popover>
              </div>

              {/* Action buttons */}
              <div className="flex items-center gap-2">
                {isAssigned ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    className="flex-1 hover:bg-primary/10 hover:text-primary"
                    onClick={(e) => {
                      e.stopPropagation();
                      onUnassignQuelle(quelle.id);
                      setSelectedId(null);
                    }}
                    disabled={unassigningQuelleIds.includes(quelle.id)}
                  >
                    Aus Kapitel entfernen
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    className="flex-1"
                    onClick={(e) => {
                      e.stopPropagation();
                      onAssignQuelle(quelle.id);
                      setSelectedId(null);
                    }}
                    disabled={assigningQuelleIds.includes(quelle.id)}
                  >
                    Hinzufügen
                  </Button>
                )}
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8"
                  onClick={(e) => {
                    e.stopPropagation();
                    onViewQuelle(quelle);
                  }}
                >
                  <Eye className="h-4 w-4" />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8 text-destructive hover:text-destructive"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteQuelle(quelle.id, quelle.name);
                  }}
                  disabled={deletingQuelleIds.includes(quelle.id)}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </div>
      </Card>
    );
  };

  return (
    <>
      <div className="w-[420px] border-l border-border bg-background flex flex-col h-full">
        {/* Header */}
        <div className="p-4 border-b border-border">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h3 className="font-semibold">Quellen</h3>
              <p className="text-xs text-muted-foreground">
                {quellen.length} gesamt
              </p>
            </div>
            <div className="flex items-center gap-1">
              <Button
                size="icon"
                variant="ghost"
                className="h-8 w-8"
                onClick={() => router.push("/quellen-manager")}
              >
                <Settings className="h-4 w-4" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                className="h-8 w-8"
                onClick={onClose}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>

          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Quellen durchsuchen..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9"
            />
          </div>
        </div>

        {/* Quellen List */}
        <div className="flex-1 overflow-y-auto p-4">
          {/* Assigned Section */}
          {assignedQuellen.length > 0 && (
            <div className="mb-4">
              <div className="flex items-center gap-2 mb-2">
                <div className="w-2 h-2 rounded-full bg-primary" />
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  In diesem Kapitel ({assignedQuellen.length})
                </span>
              </div>
              <div className="space-y-2">
                {assignedQuellen.map((quelle) =>
                  renderQuelleCard(quelle, true)
                )}
              </div>
            </div>
          )}

          {/* Unassigned Section */}
          {unassignedQuellen.length > 0 && (
            <div className="mt-6">
              <div className="flex items-center gap-2 mb-2">
                <div className="w-2 h-2 rounded-full bg-muted-foreground/30" />
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  Verfügbar ({unassignedQuellen.length})
                </span>
              </div>
              <div className="space-y-2">
                {unassignedQuellen.map((quelle) =>
                  renderQuelleCard(quelle, false)
                )}
              </div>
            </div>
          )}

          {filteredQuellen.length === 0 && (
            <div className="text-center py-8 text-muted-foreground">
              <p className="text-sm">Keine Quellen gefunden</p>
            </div>
          )}
        </div>

        {/* Add Quelle Button */}
        <div className="p-4 border-t border-border">
          <Button className="w-full" onClick={() => setIsAddDialogOpen(true)}>
            <Plus className="h-4 w-4 mr-2" />
            Neue Quelle
          </Button>
        </div>
      </div>

      {/* Add Quelle Dialog */}
      <Dialog open={isAddDialogOpen} onOpenChange={setIsAddDialogOpen}>
        <DialogContent className="!w-[80vw] !max-w-[1100px] !h-[70vh] flex flex-col p-0">
          <DialogHeader className="px-6 pt-6 pb-4 shrink-0">
            <DialogTitle>Neue Quelle hinzufügen</DialogTitle>
          </DialogHeader>

          <div className="grid grid-cols-[380px_1fr] gap-6 px-6 flex-1 min-h-0">
            {/* Left Column */}
            <div className="space-y-4 overflow-y-auto pr-2">
              {/* Image Upload Section */}
              <div className="space-y-3">
                <Label>Bilder (optional, max. 9)</Label>

                {/* Upload Mode Tabs */}
                <div className="inline-flex gap-0 border rounded-md overflow-hidden w-full">
                  <button
                    type="button"
                    className={cn(
                      "flex-1 px-3 py-2 text-sm font-medium transition-colors",
                      imageUploadMode === "upload"
                        ? "bg-primary text-primary-foreground"
                        : "bg-background hover:bg-muted"
                    )}
                    onClick={() => setImageUploadMode("upload")}
                  >
                    <svg
                      className="h-4 w-4 inline-block mr-1.5"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                      />
                    </svg>
                    Hochladen
                  </button>
                  <button
                    type="button"
                    className={cn(
                      "flex-1 px-3 py-2 text-sm font-medium transition-colors border-l",
                      imageUploadMode === "url"
                        ? "bg-primary text-primary-foreground"
                        : "bg-background hover:bg-muted"
                    )}
                    onClick={() => setImageUploadMode("url")}
                  >
                    <svg
                      className="h-4 w-4 inline-block mr-1.5"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"
                      />
                    </svg>
                    URL
                  </button>
                </div>

                {/* File Upload */}
                {imageUploadMode === "upload" && (
                  <div
                    className={cn(
                      "border-2 border-dashed rounded-lg p-6 text-center transition-colors cursor-pointer",
                      isDragging
                        ? "border-primary bg-primary/5"
                        : "border-border hover:border-primary/50"
                    )}
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                    onDrop={handleDrop}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <svg
                      className="h-10 w-10 mx-auto mb-2 text-muted-foreground"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={1.5}
                        d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                      />
                    </svg>
                    <p className="text-sm text-muted-foreground">
                      Klicken oder Dateien hierher ziehen
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">
                      Noch 9 Bilder möglich
                    </p>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="image/*"
                      multiple
                      className="hidden"
                      onChange={handleFileInput}
                    />
                  </div>
                )}

                {/* URL Input */}
                {imageUploadMode === "url" && (
                  <div className="flex gap-2">
                    <Input
                      placeholder="Bild-URL eingeben..."
                      value={imageUrl}
                      onChange={(e) => setImageUrl(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          if (imageUrl) {
                            // For URL mode, we would need to fetch and convert to File
                            // For now, just add to images array
                            void handleAddImageUrl();
                          }
                        }
                      }}
                      disabled={isAddingImageUrl}
                    />
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => {
                        if (imageUrl) {
                          void handleAddImageUrl();
                        }
                      }}
                      disabled={!imageUrl || newQuelleImages.length >= 9 || isAddingImageUrl}
                    >
                      {isAddingImageUrl ? "Lädt..." : "Hinzufügen"}
                    </Button>
                  </div>
                )}

                {/* Image Preview Grid */}
                {newQuelleImages.length > 0 && (
                  <div className="grid grid-cols-3 gap-2">
                    {newQuelleImages.map((file, index) => (
                      <div
                        key={index}
                        className="relative group aspect-square rounded-md overflow-hidden border bg-muted"
                      >
                        <img
                          src={URL.createObjectURL(file)}
                          alt={`Bild ${index + 1}`}
                          className="w-full h-full object-cover"
                        />
                        <button
                          type="button"
                          className="absolute top-1 right-1 bg-destructive text-destructive-foreground rounded-full p-1 opacity-0 group-hover:opacity-100 transition-opacity"
                          onClick={() => removeImage(index)}
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Advanced Fields Toggle */}
              <div className="flex items-center justify-between">
                <Label>Erweiterte Felder anzeigen</Label>
                <Switch
                  checked={isAdvancedMode}
                  onCheckedChange={setIsAdvancedMode}
                />
              </div>

              {/* Name Field */}
              <div className="space-y-2">
                <Label htmlFor="name">Name</Label>
                <Input
                  id="name"
                  value={newQuelleName}
                  onChange={(e) => setNewQuelleName(e.target.value)}
                  placeholder="z.B. Schmidt (2023) - Kapitel 3"
                />
              </div>

              {/* Zitierhinweis */}
              <div className="space-y-2">
                <Label>Quelle (optional)</Label>
                <Textarea
                  value={zitat}
                  onChange={(e) => setZitat(e.target.value)}
                  placeholder="z.B. Schmidt, M. (2023). Titel. Journal ..."
                  rows={2}
                  className="resize-none"
                />
              </div>

              <div className="space-y-2">
                <Label>Im Prompt verwenden</Label>
                <Select
                  value={zitatModus}
                  onValueChange={(value) => setZitatModus(value as QuelleZitatModus)}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Auswählen..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="auto">Automatisch (Autor+Jahr &gt; Vollzitat)</SelectItem>
                    <SelectItem value="authorYear">Autor + Jahr</SelectItem>
                    <SelectItem value="full">Vollzitat</SelectItem>
                    <SelectItem value="none">Nicht einfügen</SelectItem>
                  </SelectContent>
                </Select>
                {(() => {
                  const preview = computeQuelleZitatPreview({
                    autor: isAdvancedMode ? advancedFieldValues.autor : undefined,
                    jahr: isAdvancedMode ? advancedFieldValues.jahr : undefined,
                    zitat,
                    modus: zitatModus,
                  });

                  if (!preview.value) {
                    return (
                      <p className="text-xs text-muted-foreground">
                        Kein Zitierhinweis wird beim Verarbeiten in den Prompt eingefügt.
                      </p>
                    );
                  }

                  return (
                    <p className="text-xs text-muted-foreground break-words">
                      Wird beim Verarbeiten im Prompt eingefügt: {preview.value}
                    </p>
                  );
                })()}
              </div>

              {/* Advanced fields - Typ, Jahr, Autor */}
              {isAdvancedMode && (
                <>
                  <div className="space-y-2">
                    <Label>Typ</Label>
                    <Select
                      value={advancedFieldValues.typ || ""}
                      onValueChange={(value) =>
                        setAdvancedFieldValues({
                          ...advancedFieldValues,
                          typ: value,
                        })
                      }
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Auswählen..." />
                      </SelectTrigger>
                      <SelectContent>
                        {QUELLE_TYPES.map((option) => (
                          <SelectItem key={option} value={option}>
                            {option}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-2">
                    <Label>Jahr</Label>
                    <Input
                      type="number"
                      placeholder="z.B. 2023"
                      value={advancedFieldValues.jahr || ""}
                      onChange={(e) =>
                        setAdvancedFieldValues({
                          ...advancedFieldValues,
                          jahr:
                            e.target.value.trim().length === 0
                              ? undefined
                              : Number(e.target.value),
                        })
                      }
                    />
                  </div>

                  <div className="space-y-2">
                    <Label>Autor</Label>
                    <Input
                      type="text"
                      placeholder="z.B. Schmidt, M."
                      value={advancedFieldValues.autor || ""}
                      onChange={(e) =>
                        setAdvancedFieldValues({
                          ...advancedFieldValues,
                          autor: e.target.value,
                        })
                      }
                    />
                  </div>

                  {/* URL and Zugriff am - only if advanced */}
                  <div className="space-y-2">
                    <Label>URL</Label>
                    <Input
                      type="url"
                      placeholder="https://..."
                      value={advancedFieldValues.url || ""}
                      onChange={(e) =>
                        setAdvancedFieldValues({
                          ...advancedFieldValues,
                          url: e.target.value,
                        })
                      }
                    />
                  </div>

                  <div className="space-y-2">
                    <Label>Zugriff am</Label>
                    <Input
                      type="date"
                      value={advancedFieldValues.zugriffAm || ""}
                      onChange={(e) =>
                        setAdvancedFieldValues({
                          ...advancedFieldValues,
                          zugriffAm: e.target.value,
                        })
                      }
                    />
                  </div>
                </>
              )}

              {/* Color picker */}
              <div>
                <Label>Farbe</Label>
                <div className="flex flex-wrap gap-1.5 mt-2">
                  <button
                    type="button"
                    className={cn(
                      "w-8 h-8 rounded-full border-2 flex items-center justify-center transition-colors",
                      !newQuelleColor
                        ? "border-primary bg-muted"
                        : "border-border hover:border-muted-foreground"
                    )}
                    onClick={() => setNewQuelleColor(null)}
                    title="Keine Farbe"
                  >
                    <X className="h-4 w-4 text-muted-foreground" />
                  </button>
                  {QUELLE_COLORS.map((color) => (
                    <button
                      key={color}
                      type="button"
                      className={cn(
                        "w-8 h-8 rounded-full border-2 flex items-center justify-center transition-colors",
                        newQuelleColor === color
                          ? "border-primary ring-2 ring-primary/20"
                          : "border-transparent hover:border-muted-foreground"
                      )}
                      style={{ backgroundColor: colorMap[color] }}
                      onClick={() => setNewQuelleColor(color)}
                      title={colorLabels[color]}
                    >
                      {newQuelleColor === color && (
                        <Check className="h-4 w-4 text-foreground/70" />
                      )}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Right Column - Text */}
            <div className="flex flex-col h-full">
              <Label htmlFor="text" className="mb-2">
                Text
              </Label>
              <Textarea
                id="text"
                value={newQuelleText}
                onChange={(e) => setNewQuelleText(e.target.value)}
                className="resize-none flex-1 min-h-0 overflow-y-auto"
                placeholder="Füge hier den relevanten Text aus deiner Quelle ein..."
              />
            </div>
          </div>

          <DialogFooter className="px-6 py-4 border-t shrink-0">
            <Button variant="outline" onClick={() => setIsAddDialogOpen(false)}>
              Abbrechen
            </Button>
            <Button
              onClick={handleAddQuelle}
              disabled={!newQuelleName || !newQuelleText || isAddingQuelle}
            >
              {isAddingQuelle ? "Wird hinzugefügt..." : "Hinzufügen"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
