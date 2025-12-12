"use client";

import { useState, useRef } from "react";
import {
  X,
  Plus,
  Trash2,
  Eye,
  BookOpen,
  Search,
  CheckCircle2,
  Circle,
  Upload,
  Link as LinkIcon,
  ImageIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import type { Quelle } from "@/app/types/ui";

interface QuellenPanelProps {
  quellen: Quelle[];
  assignedQuellenIds: string[];
  onClose: () => void;
  onAddQuelle: (name: string, text: string, imageFiles?: File[]) => Promise<void>;
  onDeleteQuelle: (id: string, name: string) => void;
  onAssignQuelle: (id: string) => Promise<void>;
  onUnassignQuelle: (id: string) => Promise<void>;
  onViewQuelle: (quelle: Quelle) => void;
}

export function QuellenPanel({
  quellen,
  assignedQuellenIds,
  onClose,
  onAddQuelle,
  onDeleteQuelle,
  onAssignQuelle,
  onUnassignQuelle,
  onViewQuelle,
}: QuellenPanelProps) {
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [newQuelleName, setNewQuelleName] = useState("");
  const [newQuelleText, setNewQuelleText] = useState("");
  const [newQuelleImages, setNewQuelleImages] = useState<string[]>([]);
  const [newQuelleImageFiles, setNewQuelleImageFiles] = useState<File[]>([]);
  const [imageUrl, setImageUrl] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleAddQuelle = async () => {
    if (newQuelleName.trim() && newQuelleText.trim()) {
      await onAddQuelle(newQuelleName.trim(), newQuelleText.trim(), newQuelleImageFiles);
      setNewQuelleName("");
      setNewQuelleText("");
      setNewQuelleImages([]);
      setNewQuelleImageFiles([]);
      setAddDialogOpen(false);
    }
  };

  // Process files (used by both file input and drag-drop)
  const processFiles = (files: FileList | File[]) => {
    const remaining = 9 - newQuelleImages.length;
    const filesToProcess = Array.from(files).slice(0, remaining);

    // Validate file type and size
    const validTypes = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'];
    const maxSize = 5 * 1024 * 1024; // 5MB

    const validFiles: File[] = [];

    for (const file of filesToProcess) {
      if (!validTypes.includes(file.type)) {
        toast.error(`Ungültiger Dateityp: ${file.name}`, {
          description: 'Nur JPG, PNG, WebP und GIF sind erlaubt.',
        });
        continue;
      }
      if (file.size > maxSize) {
        toast.error(`Datei zu groß: ${file.name}`, {
          description: `Maximale Größe: 5MB (aktuell: ${(file.size / 1024 / 1024).toFixed(2)}MB)`,
        });
        continue;
      }
      validFiles.push(file);
    }

    // Store File objects
    setNewQuelleImageFiles((prev) => [...prev, ...validFiles]);

    // Create preview URLs
    validFiles.forEach((file) => {
      const reader = new FileReader();
      reader.onload = (event) => {
        if (event.target?.result) {
          setNewQuelleImages((prev) => [
            ...prev,
            event.target!.result as string,
          ]);
        }
      };
      reader.readAsDataURL(file);
    });
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;

    processFiles(files);

    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      processFiles(files);
    }
  };

  const handleAddImageUrl = () => {
    if (imageUrl.trim() && newQuelleImages.length < 9) {
      setNewQuelleImages((prev) => [...prev, imageUrl.trim()]);
      setImageUrl("");
    }
  };

  const handleRemoveImage = (index: number) => {
    setNewQuelleImages((prev) => prev.filter((_, i) => i !== index));
    setNewQuelleImageFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleViewQuelle = (quelle: Quelle) => {
    onViewQuelle(quelle);
  };

  // Filter quellen by search query
  const filteredQuellen = quellen.filter((q) =>
    q.name.toLowerCase().includes(searchQuery.toLowerCase())
  );
  const assignedQuellen = filteredQuellen.filter((q) =>
    assignedQuellenIds.includes(q.id)
  );
  const unassignedQuellen = filteredQuellen.filter(
    (q) => !assignedQuellenIds.includes(q.id)
  );

  return (
    <>
      <div className="w-[420px] border-l border-border bg-background flex flex-col h-full">
        {/* Header */}
        <div className="p-4 border-b border-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BookOpen className="h-5 w-5 text-muted-foreground" />
            <h2 className="font-medium">Quellen</h2>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* Search Bar */}
        <div className="px-4 pt-4">
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

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-6">
          {/* Assigned Section */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <div className="w-2 h-2 rounded-full bg-primary" />
              <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                In diesem Kapitel ({assignedQuellen.length})
              </span>
            </div>
            {assignedQuellen.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">
                Keine Quellen zugewiesen
              </p>
            ) : (
              <div className="space-y-2">
                {assignedQuellen.map((quelle) => (
                  <Card
                    key={quelle.id}
                    className={cn(
                      "p-3 cursor-pointer transition-all border-primary/30 bg-primary/5",
                      selectedId === quelle.id && "ring-2 ring-primary"
                    )}
                    onClick={() =>
                      setSelectedId(selectedId === quelle.id ? null : quelle.id)
                    }
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-medium truncate">
                            {quelle.name}
                          </p>
                          {quelle.images && quelle.images.length > 0 && (
                            <ImageIcon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground">
                          {quelle.text
                            .split(/\s+/)
                            .filter(Boolean)
                            .length.toLocaleString("de-DE")}{" "}
                          Wörter
                        </p>
                      </div>
                      <CheckCircle2 className="h-5 w-5 text-primary shrink-0 ml-2" />
                    </div>
                    {selectedId === quelle.id && (
                      <div className="mt-3 pt-3 border-t border-border flex items-center gap-2">
                        <Button
                          size="sm"
                          variant="destructive"
                          className="flex-1"
                          onClick={(e) => {
                            e.stopPropagation();
                            onUnassignQuelle(quelle.id);
                            setSelectedId(null);
                          }}
                        >
                          Entfernen
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleViewQuelle(quelle);
                          }}
                        >
                          <Eye className="h-4 w-4" />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-destructive hover:text-destructive"
                          onClick={(e) => {
                            e.stopPropagation();
                            onDeleteQuelle(quelle.id, quelle.name);
                          }}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    )}
                  </Card>
                ))}
              </div>
            )}
          </div>

          {/* Unassigned Section */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <div className="w-2 h-2 rounded-full bg-muted-foreground/30" />
              <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Verfügbar ({unassignedQuellen.length})
              </span>
            </div>
            {unassignedQuellen.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">
                Alle Quellen sind zugewiesen
              </p>
            ) : (
              <div className="space-y-2">
                {unassignedQuellen.map((quelle) => (
                  <Card
                    key={quelle.id}
                    className={cn(
                      "p-3 cursor-pointer transition-all hover:border-primary/30",
                      selectedId === quelle.id && "ring-2 ring-primary"
                    )}
                    onClick={() =>
                      setSelectedId(selectedId === quelle.id ? null : quelle.id)
                    }
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-medium truncate">
                            {quelle.name}
                          </p>
                          {quelle.images && quelle.images.length > 0 && (
                            <ImageIcon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground">
                          {quelle.text
                            .split(/\s+/)
                            .filter(Boolean)
                            .length.toLocaleString("de-DE")}{" "}
                          Wörter
                        </p>
                      </div>
                      <Circle className="h-5 w-5 text-muted-foreground/30 shrink-0 ml-2" />
                    </div>
                    {selectedId === quelle.id && (
                      <div className="mt-3 pt-3 border-t border-border flex items-center gap-2">
                        <Button
                          size="sm"
                          className="flex-1"
                          onClick={(e) => {
                            e.stopPropagation();
                            onAssignQuelle(quelle.id);
                            setSelectedId(null);
                          }}
                        >
                          <Plus className="h-4 w-4 mr-1" />
                          Hinzufügen
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleViewQuelle(quelle);
                          }}
                        >
                          <Eye className="h-4 w-4" />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-destructive hover:text-destructive"
                          onClick={(e) => {
                            e.stopPropagation();
                            onDeleteQuelle(quelle.id, quelle.name);
                          }}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    )}
                  </Card>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Add Button */}
        <div className="p-4 border-t border-border">
          <Button className="w-full" onClick={() => setAddDialogOpen(true)}>
            <Plus className="h-4 w-4 mr-2" />
            Neue Quelle hinzufügen
          </Button>
        </div>
      </div>

      {/* Add Quelle Dialog */}
      <Dialog open={addDialogOpen} onOpenChange={setAddDialogOpen}>
        <DialogContent className="sm:max-w-2xl [&>button]:hidden">
          <DialogHeader>
            <DialogTitle>Neue Quelle hinzufügen</DialogTitle>
          </DialogHeader>
          <div className="py-4 space-y-4">
            <div>
              <Label className="text-sm text-muted-foreground">
                Bilder{" "}
                <span className="font-normal">(optional, max. 9)</span>
              </Label>

              {newQuelleImages.length > 0 && (
                <div className="grid grid-cols-3 gap-2 mt-2 mb-3">
                  {newQuelleImages.map((img, index) => (
                    <div
                      key={index}
                      className="relative aspect-square rounded-lg overflow-hidden border bg-muted"
                    >
                      <img
                        src={img}
                        alt={`Bild ${index + 1}`}
                        className="w-full h-full object-cover"
                      />
                      <button
                        onClick={() => handleRemoveImage(index)}
                        className="absolute top-1 right-1 w-6 h-6 rounded-full bg-white text-black flex items-center justify-center hover:bg-white/90 shadow-md"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {newQuelleImages.length < 9 && (
                <Tabs defaultValue="upload" className="mt-2">
                  <TabsList className="grid w-full grid-cols-2 h-9">
                    <TabsTrigger value="upload" className="text-xs">
                      <Upload className="h-3 w-3 mr-1" />
                      Hochladen
                    </TabsTrigger>
                    <TabsTrigger value="url" className="text-xs">
                      <LinkIcon className="h-3 w-3 mr-1" />
                      URL
                    </TabsTrigger>
                  </TabsList>
                  <TabsContent value="upload" className="mt-2">
                    <div
                      className={`border-2 border-dashed rounded-lg p-4 text-center cursor-pointer transition-colors ${
                        isDragging
                          ? 'bg-primary/10 border-primary'
                          : 'bg-muted/30 hover:bg-muted/50'
                      }`}
                      onClick={() => fileInputRef.current?.click()}
                      onDragEnter={handleDragEnter}
                      onDragOver={handleDragOver}
                      onDragLeave={handleDragLeave}
                      onDrop={handleDrop}
                    >
                      <Upload
                        className={`h-6 w-6 mx-auto mb-2 transition-colors ${
                          isDragging ? 'text-primary' : 'text-muted-foreground'
                        }`}
                      />
                      <p
                        className={`text-sm transition-colors ${
                          isDragging ? 'text-primary' : 'text-muted-foreground'
                        }`}
                      >
                        {isDragging
                          ? 'Dateien hier ablegen...'
                          : 'Klicken zum Hochladen oder Dateien hierher ziehen'}
                      </p>
                      <p className="text-xs text-muted-foreground/70 mt-1">
                        JPG, PNG, WebP, GIF (max. 5MB)
                      </p>
                    </div>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="image/*"
                      multiple
                      className="hidden"
                      onChange={handleFileUpload}
                    />
                  </TabsContent>
                  <TabsContent value="url" className="mt-2">
                    <div className="flex gap-2">
                      <Input
                        placeholder="https://beispiel.de/bild.jpg"
                        value={imageUrl}
                        onChange={(e) => setImageUrl(e.target.value)}
                        onKeyDown={(e) =>
                          e.key === "Enter" && handleAddImageUrl()
                        }
                      />
                      <Button
                        size="sm"
                        onClick={handleAddImageUrl}
                        disabled={!imageUrl.trim()}
                      >
                        Hinzufügen
                      </Button>
                    </div>
                  </TabsContent>
                </Tabs>
              )}
            </div>

            <div>
              <Label htmlFor="quelle-name" className="text-sm text-muted-foreground">
                Name der Quelle
              </Label>
              <Input
                id="quelle-name"
                value={newQuelleName}
                onChange={(e) => setNewQuelleName(e.target.value)}
                placeholder="z.B. Müller (2023): Digitale Transformation"
                className="mt-2"
              />
            </div>
            <div>
              <Label htmlFor="quelle-text" className="text-sm text-muted-foreground">
                Text der Quelle (bis zu 4000+ Wörter)
              </Label>
              <Textarea
                id="quelle-text"
                value={newQuelleText}
                onChange={(e) => setNewQuelleText(e.target.value)}
                placeholder="Füge hier den relevanten Textabschnitt aus deiner Quelle ein..."
                className="mt-2 h-[200px] min-h-[200px] max-h-[200px] resize-none font-mono text-sm overflow-y-auto"
              />
              <div className="mt-2 text-xs text-muted-foreground">
                {newQuelleText.split(/\s+/).filter(Boolean).length} Wörter
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddDialogOpen(false)}>
              Abbrechen
            </Button>
            <Button
              onClick={handleAddQuelle}
              disabled={!newQuelleName.trim() || !newQuelleText.trim()}
            >
              Quelle hinzufügen
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
