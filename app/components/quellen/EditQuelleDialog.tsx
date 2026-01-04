"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Loader2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

import {
  getQuelle,
  getQuelleContent,
  type ImageMetadata,
} from "@/app/actions/quellen";
import {
  QUELLE_COLORS,
  QUELLE_TYPES,
  colorLabels,
  colorMap,
  type QuelleColor,
} from "@/app/lib/quellen/fieldConfig";
import {
  getQuellenModeAdvanced,
  setQuellenModeAdvanced,
} from "@/app/lib/storage/preferences";

type SavePayload = {
  quelleId: string;
  name: string;
  text: string;
  keptImages: ImageMetadata[];
  newImageFiles: File[];
  removedImagePaths: string[];
  advancedFields: {
    autor?: string | null;
    jahr?: number | null;
    typ?: (typeof QUELLE_TYPES)[number] | null;
    url?: string | null;
    zugriffAm?: string | null;
    color?: QuelleColor | null;
  };
};

interface EditQuelleDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  quelleId: string | null;
  onSave: (payload: SavePayload) => Promise<boolean>;
}

const MAX_IMAGES = 9;

type AdvancedFieldValues = {
  autor: string;
  jahr?: number;
  typ: string;
  url: string;
  zugriffAm: string;
};

function toNullableTrimmedString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function toNullableNumber(value: unknown): number | null {
  if (typeof value !== "number") return null;
  if (Number.isNaN(value)) return null;
  return value;
}

export function EditQuelleDialog({
  open,
  onOpenChange,
  quelleId,
  onSave,
}: EditQuelleDialogProps) {
  const [isAdvancedMode, setIsAdvancedMode] = useState(() =>
    getQuellenModeAdvanced()
  );
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const [existingImages, setExistingImages] = useState<ImageMetadata[]>([]);
  const [removedImagePaths, setRemovedImagePaths] = useState<string[]>([]);
  const [newImageFiles, setNewImageFiles] = useState<File[]>([]);
  const [newImagePreviews, setNewImagePreviews] = useState<string[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [advancedFieldValues, setAdvancedFieldValues] =
    useState<AdvancedFieldValues>({
      autor: "",
      jahr: undefined,
      typ: "",
      url: "",
      zugriffAm: "",
    });
  const [color, setColor] = useState<QuelleColor | null>(null);

  useEffect(() => {
    setQuellenModeAdvanced(isAdvancedMode);
  }, [isAdvancedMode]);

  useEffect(() => {
    const urls = newImageFiles.map((file) => URL.createObjectURL(file));
    setNewImagePreviews(urls);
    return () => {
      urls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [newImageFiles]);

  useEffect(() => {
    if (!open || !quelleId) return;

    let cancelled = false;
    setIsLoading(true);
    setIsSaving(false);

    (async () => {
      try {
        const [meta, content] = await Promise.all([
          getQuelle(quelleId),
          getQuelleContent(quelleId),
        ]);

        if (cancelled) return;
        if (!meta) {
          toast.error("Quelle nicht gefunden");
          onOpenChange(false);
          return;
        }

        setName(meta.title || "");
        setText(content?.text || "");
        setExistingImages(meta.images || []);
        setRemovedImagePaths([]);
        setNewImageFiles([]);
        setColor((meta.color as QuelleColor | undefined) ?? null);
        setAdvancedFieldValues({
          autor: meta.autor ?? "",
          jahr: meta.jahr ?? undefined,
          typ: meta.typ ?? "",
          url: meta.url ?? "",
          zugriffAm: meta.zugriffAm ?? "",
        });
      } catch {
        if (cancelled) return;
        toast.error("Fehler beim Laden der Quelle");
        onOpenChange(false);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [open, quelleId, onOpenChange]);

  const remainingSlots = Math.max(
    0,
    MAX_IMAGES - existingImages.length - newImageFiles.length
  );

  const handleFiles = (files: File[]) => {
    const imageFiles = files.filter((f) => f.type.startsWith("image/"));
    if (imageFiles.length === 0) return;
    if (remainingSlots <= 0) return;

    setNewImageFiles((prev) => {
      const slots = Math.max(0, MAX_IMAGES - existingImages.length - prev.length);
      const toAdd = imageFiles.slice(0, slots);
      return toAdd.length > 0 ? [...prev, ...toAdd] : prev;
    });
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    if (remainingSlots <= 0) return;
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (remainingSlots <= 0) return;
    handleFiles(Array.from(e.dataTransfer.files));
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files) return;
    handleFiles(Array.from(e.target.files));
    e.target.value = "";
  };

  const removeExistingImage = (index: number) => {
    setExistingImages((prev) => {
      const img = prev[index];
      if (img?.path) {
        setRemovedImagePaths((paths) => [...paths, img.path]);
      }
      return prev.filter((_, i) => i !== index);
    });
  };

  const removeNewImage = (index: number) => {
    setNewImageFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSave = async () => {
    if (!quelleId || isSaving) return;
    if (!name.trim() || !text.trim()) return;

    setIsSaving(true);
    try {
      const advancedFields: SavePayload["advancedFields"] = {
        color,
      };

      if (isAdvancedMode) {
        advancedFields.autor = toNullableTrimmedString(advancedFieldValues.autor);
        advancedFields.jahr = toNullableNumber(advancedFieldValues.jahr);
        advancedFields.typ =
          (toNullableTrimmedString(advancedFieldValues.typ) as SavePayload["advancedFields"]["typ"]) ??
          null;
        advancedFields.url = toNullableTrimmedString(advancedFieldValues.url);
        advancedFields.zugriffAm = toNullableTrimmedString(
          advancedFieldValues.zugriffAm
        );
      }

      const success = await onSave({
        quelleId,
        name: name.trim(),
        text,
        keptImages: existingImages,
        newImageFiles,
        removedImagePaths,
        advancedFields,
      });

      if (success) {
        onOpenChange(false);
      }
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && isSaving) return;
        onOpenChange(nextOpen);
      }}
    >
      <DialogContent className="!w-[80vw] !max-w-[1100px] !h-[70vh] flex flex-col p-0">
        <div className="relative flex flex-col h-full">
          <DialogHeader className="px-6 pt-6 pb-4 shrink-0">
            <DialogTitle>Quelle bearbeiten</DialogTitle>
          </DialogHeader>

          <div className="grid grid-cols-[380px_1fr] gap-6 px-6 flex-1 min-h-0">
            {/* Left Column */}
            <div className="space-y-4 overflow-y-auto pr-2">
              {/* Images */}
              <div className="space-y-3">
                <Label>Bilder (optional, max. {MAX_IMAGES})</Label>

                <div
                  className={cn(
                    "border-2 border-dashed rounded-lg p-6 text-center transition-colors cursor-pointer",
                    remainingSlots <= 0 && "opacity-50 cursor-not-allowed",
                    remainingSlots > 0 &&
                      (isDragging
                        ? "border-primary bg-primary/5"
                        : "border-border hover:border-primary/50")
                  )}
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                  onClick={() =>
                    remainingSlots > 0 && fileInputRef.current?.click()
                  }
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
                    {remainingSlots > 0
                      ? "Klicken oder Dateien hierher ziehen"
                      : "Maximale Bildanzahl erreicht"}
                  </p>
                  <p className="text-xs text-muted-foreground mt-1">
                    Noch {remainingSlots} Bild(er) m”glich
                  </p>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/*"
                    multiple
                    className="hidden"
                    onChange={handleFileInput}
                    disabled={remainingSlots <= 0}
                  />
                </div>

                {(existingImages.length > 0 || newImagePreviews.length > 0) && (
                  <div className="grid grid-cols-3 gap-2">
                    {existingImages.map((img, index) => (
                      <div
                        key={img.path || img.url || index}
                        className="relative group aspect-square rounded-md overflow-hidden border bg-muted"
                      >
                        <img
                          src={img.url}
                          alt={`Bild ${index + 1}`}
                          className="w-full h-full object-cover"
                        />
                        <button
                          type="button"
                          className="absolute top-1 right-1 bg-destructive text-destructive-foreground rounded-full p-1 opacity-0 group-hover:opacity-100 transition-opacity"
                          onClick={() => removeExistingImage(index)}
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </div>
                    ))}
                    {newImagePreviews.map((previewUrl, index) => (
                      <div
                        key={previewUrl}
                        className="relative group aspect-square rounded-md overflow-hidden border bg-muted"
                      >
                        <img
                          src={previewUrl}
                          alt={`Neues Bild ${index + 1}`}
                          className="w-full h-full object-cover"
                        />
                        <button
                          type="button"
                          className="absolute top-1 right-1 bg-destructive text-destructive-foreground rounded-full p-1 opacity-0 group-hover:opacity-100 transition-opacity"
                          onClick={() => removeNewImage(index)}
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
                <Switch checked={isAdvancedMode} onCheckedChange={setIsAdvancedMode} />
              </div>

              {/* Name Field */}
              <div className="space-y-2">
                <Label htmlFor="edit-name">Name</Label>
                <Input
                  id="edit-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="z.B. Schmidt (2023) - Kapitel 3"
                />
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
                        <SelectValue placeholder="Ausw„hlen..." />
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
                      value={advancedFieldValues.jahr ?? ""}
                      onChange={(e) => {
                        const raw = e.target.value;
                        setAdvancedFieldValues({
                          ...advancedFieldValues,
                          jahr: raw.trim().length === 0 ? undefined : Number(raw),
                        });
                      }}
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
                      !color
                        ? "border-primary bg-muted"
                        : "border-border hover:border-muted-foreground"
                    )}
                    onClick={() => setColor(null)}
                    title="Keine Farbe"
                  >
                    <X className="h-4 w-4 text-muted-foreground" />
                  </button>
                  {QUELLE_COLORS.map((c) => (
                    <button
                      key={c}
                      type="button"
                      className={cn(
                        "w-8 h-8 rounded-full border-2 flex items-center justify-center transition-colors",
                        color === c
                          ? "border-primary ring-2 ring-primary/20"
                          : "border-transparent hover:border-muted-foreground"
                      )}
                      style={{ backgroundColor: colorMap[c] }}
                      onClick={() => setColor(c)}
                      title={colorLabels[c]}
                    >
                      {color === c && (
                        <Check className="h-4 w-4 text-foreground/70" />
                      )}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Right Column - Text */}
            <div className="flex flex-col h-full">
              <Label htmlFor="edit-text" className="mb-2">
                Text
              </Label>
              <Textarea
                id="edit-text"
                value={text}
                onChange={(e) => setText(e.target.value)}
                className="resize-none flex-1 min-h-0 overflow-y-auto"
                placeholder="Fge hier den relevanten Text aus deiner Quelle ein..."
              />
            </div>
          </div>

          <DialogFooter className="px-6 py-4 border-t shrink-0">
            <Button
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={isSaving}
            >
              Abbrechen
            </Button>
            <Button
              onClick={handleSave}
              disabled={isLoading || isSaving || !name.trim() || !text.trim()}
            >
              {isSaving ? "Speichern..." : "Speichern"}
            </Button>
          </DialogFooter>

          {isLoading && (
            <div className="absolute inset-0 bg-background/70 backdrop-blur-sm flex items-center justify-center">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Quelle wird geladen...
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
