"use client";

import { useEffect, useRef, useState } from "react";
import { Check, X } from "lucide-react";

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

interface AddQuelleDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAddQuelle: (
    name: string,
    text: string,
    imageFiles?: File[],
    advancedFields?: Record<string, any>
  ) => Promise<boolean>;
  isAddingQuelle: boolean;
}

export function AddQuelleDialog({
  open,
  onOpenChange,
  onAddQuelle,
  isAddingQuelle,
}: AddQuelleDialogProps) {
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

  // Image upload state
  const [imageUploadMode, setImageUploadMode] = useState<"upload" | "url">(
    "upload"
  );
  const [imageUrl, setImageUrl] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Persist advanced mode preference
  useEffect(() => {
    setQuellenModeAdvanced(isAdvancedMode);
  }, [isAdvancedMode]);

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

  const handleAddQuelle = async () => {
    if (newQuelleName && newQuelleText) {
      const allAdvancedFields = isAdvancedMode
        ? { ...advancedFieldValues, color: newQuelleColor }
        : newQuelleColor
        ? { color: newQuelleColor }
        : undefined;

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
        onOpenChange(false);
      }
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
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
                          alert("URL-Modus ist in Entwicklung");
                        }
                      }
                    }}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      if (imageUrl) {
                        alert("URL-Modus ist in Entwicklung");
                      }
                    }}
                    disabled={!imageUrl || newQuelleImages.length >= 9}
                  >
                    Hinzufügen
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
              <Switch checked={isAdvancedMode} onCheckedChange={setIsAdvancedMode} />
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
                        jahr: Number(e.target.value),
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
          <Button variant="outline" onClick={() => onOpenChange(false)}>
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
  );
}

