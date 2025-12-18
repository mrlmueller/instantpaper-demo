"use client";

import { useState, useRef, useEffect } from "react";
import { X, Plus, Eye, Trash2, CheckCircle2, Circle, Search, Palette, Settings, Check, ImageIcon } from "lucide-react";
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
import { toast } from "sonner";
import { useRouter } from "next/navigation";
import type { Quelle } from "@/app/types/ui";
import { ADVANCED_FIELDS, colorMap, colorLabels, QUELLE_COLORS, type QuelleColor } from "@/app/lib/quellen/fieldConfig";
import { getQuellenModeAdvanced, setQuellenModeAdvanced } from "@/app/lib/storage/preferences";
import { updateQuelleColor } from "@/app/actions/quellen";

interface QuellenPanelProps {
  quellen: Quelle[];
  assignedQuellenIds: string[];
  onClose: () => void;
  onAddQuelle: (name: string, text: string, imageFiles?: File[], advancedFields?: Record<string, any>) => Promise<boolean>;
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
  'Book': 'Buch',
  'Article': 'Artikel',
  'Website': 'Website',
  'Thesis': 'Thesis',
  'Report': 'Report',
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

  // Advanced mode state
  const [isAdvancedMode, setIsAdvancedMode] = useState(() => getQuellenModeAdvanced());
  const [advancedFieldValues, setAdvancedFieldValues] = useState<Record<string, any>>({});

  // New quelle form state
  const [newQuelleName, setNewQuelleName] = useState("");
  const [newQuelleText, setNewQuelleText] = useState("");
  const [newQuelleImages, setNewQuelleImages] = useState<File[]>([]);

  // Persist advanced mode preference
  useEffect(() => {
    setQuellenModeAdvanced(isAdvancedMode);
  }, [isAdvancedMode]);

  // Filter and sort quellen
  const filteredQuellen = quellen.filter(
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
    const colorOrder = ["blue", "green", "teal", "lavender", "cream", "peach", "rose", null];
    const aColorIndex = colorOrder.indexOf(a.color || null);
    const bColorIndex = colorOrder.indexOf(b.color || null);
    return aColorIndex - bColorIndex;
  });

  // Separate assigned and unassigned
  const assignedQuellen = sortedQuellen.filter((q) => assignedQuellenIds.includes(q.id));
  const unassignedQuellen = sortedQuellen.filter((q) => !assignedQuellenIds.includes(q.id));

  const handleAddQuelle = async () => {
    if (newQuelleName && newQuelleText) {
      const success = await onAddQuelle(
        newQuelleName,
        newQuelleText,
        newQuelleImages.length > 0 ? newQuelleImages : undefined,
        isAdvancedMode ? advancedFieldValues : undefined
      );

      if (success) {
        setNewQuelleName("");
        setNewQuelleText("");
        setNewQuelleImages([]);
        setAdvancedFieldValues({});
        setIsAddDialogOpen(false);
      }
    }
  };

  const handleUpdateColor = async (quelleId: string, color: QuelleColor | null) => {
    // Optimistic update - refresh immediately, update in background
    router.refresh();

    setIsUpdatingColor(true);
    try {
      await updateQuelleColor(quelleId, color);
    } catch (error) {
      // Silently handle error, refresh again to revert
      router.refresh();
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
          isAssigned ? "shadow-md border-border" : "shadow-none border-border/50 bg-muted/30"
        )}
        style={{
          borderColor: isSelected ? cardColor || "hsl(var(--primary))" : undefined,
          boxShadow: isSelected
            ? `0 0 0 2px ${cardColor || "hsl(var(--primary))"}`
            : isAssigned
              ? "0 2px 8px rgba(0,0,0,0.08)"
              : undefined,
        }}
        onMouseEnter={(e) => {
          if (!isSelected) {
            e.currentTarget.style.borderColor = cardColor || "hsl(var(--primary) / 0.5)";
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
          <div className="absolute top-0 left-0 right-0 h-1.5" style={{ backgroundColor: cardColor || undefined }} />
        )}

        {/* Card content */}
        <div style={{ marginTop: quelle.color ? "6px" : "0" }}>
          <div className="flex items-center justify-between">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <p className="text-sm font-medium truncate">{quelle.name}</p>
                {quelle.images && quelle.images.length > 0 && (
                  <ImageIcon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                {quelle.text.split(/\s+/).filter(Boolean).length.toLocaleString("de-DE")} Wörter
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
                    <Button size="sm" variant="ghost" className="h-7 px-2" onClick={(e) => e.stopPropagation()}>
                      <Palette className="h-4 w-4 text-muted-foreground shrink-0" />
                      <span className="text-xs ml-1.5">Farbe</span>
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-auto p-2" align="start" onClick={(e) => e.stopPropagation()}>
                    <div className="flex flex-wrap gap-1.5 max-w-[160px]">
                      <button
                        className={cn(
                          "w-6 h-6 rounded-full border-2 flex items-center justify-center",
                          !quelle.color ? "border-primary" : "border-border hover:border-muted-foreground"
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
                            quelle.color === color ? "border-primary" : "border-transparent hover:border-muted-foreground"
                          )}
                          style={{ backgroundColor: colorMap[color] }}
                          onClick={() => handleUpdateColor(quelle.id, color)}
                        >
                          {quelle.color === color && <Check className="h-3.5 w-3.5 text-foreground/70" />}
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
                    className="flex-1"
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
              <p className="text-xs text-muted-foreground">{quellen.length} gesamt</p>
            </div>
            <div className="flex items-center gap-1">
              <Button
                size="icon"
                variant="ghost"
                className="h-8 w-8"
                onClick={() => router.push('/quellen-manager')}
              >
                <Settings className="h-4 w-4" />
              </Button>
              <Button size="icon" variant="ghost" className="h-8 w-8" onClick={onClose}>
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
                {assignedQuellen.map((quelle) => renderQuelleCard(quelle, true))}
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
                {unassignedQuellen.map((quelle) => renderQuelleCard(quelle, false))}
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
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center justify-between">
              Neue Quelle hinzufügen
              <div className="flex items-center gap-2 text-sm font-normal">
                <span className="text-muted-foreground">Erweitert</span>
                <Switch checked={isAdvancedMode} onCheckedChange={setIsAdvancedMode} />
              </div>
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-4">
            <div>
              <Label htmlFor="name">Name</Label>
              <Input
                id="name"
                value={newQuelleName}
                onChange={(e) => setNewQuelleName(e.target.value)}
                placeholder="z.B. Müller (2023)"
              />
            </div>

            <div>
              <Label htmlFor="text">Text</Label>
              <Textarea
                id="text"
                value={newQuelleText}
                onChange={(e) => setNewQuelleText(e.target.value)}
                rows={6}
                placeholder="Inhalt der Quelle..."
              />
            </div>

            {/* Advanced fields */}
            {isAdvancedMode && (
              <div className="space-y-3 pt-3 border-t">
                {ADVANCED_FIELDS.map((field) => (
                  <div key={field.key}>
                    <Label>{field.label}</Label>
                    {field.type === 'select' && field.options ? (
                      <Select
                        value={advancedFieldValues[field.key] || ""}
                        onValueChange={(value) =>
                          setAdvancedFieldValues({ ...advancedFieldValues, [field.key]: value })
                        }
                      >
                        <SelectTrigger>
                          <SelectValue placeholder={`${field.label} auswählen...`} />
                        </SelectTrigger>
                        <SelectContent>
                          {field.options.map((option) => (
                            <SelectItem key={option} value={option}>
                              {option}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <Input
                        type={field.type}
                        placeholder={field.placeholder}
                        value={advancedFieldValues[field.key] || ""}
                        onChange={(e) =>
                          setAdvancedFieldValues({
                            ...advancedFieldValues,
                            [field.key]: field.type === 'number' ? Number(e.target.value) : e.target.value,
                          })
                        }
                      />
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setIsAddDialogOpen(false)}>
              Abbrechen
            </Button>
            <Button onClick={handleAddQuelle} disabled={!newQuelleName || !newQuelleText || isAddingQuelle}>
              {isAddingQuelle ? "Wird hinzugefügt..." : "Hinzufügen"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
