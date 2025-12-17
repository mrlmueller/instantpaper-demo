'use client';

import { useState, useMemo, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { Search, Palette, BookOpen, Plus, ArrowLeft } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import type { Quelle } from '@/app/types/ui';
import type { Kapitel as FirebaseKapitel } from '@/app/actions/kapitels';
import { transformQuelleToUI } from '@/app/lib/transformers/ui-data';
import { updateQuelleColor, bulkAssignQuellen } from '@/app/actions/quellen';
import { QUELLE_COLORS, COLOR_CLASSES, QUELLE_TYPES, type QuelleColor } from '@/app/lib/quellen/fieldConfig';
import { cn } from '@/lib/utils';

interface QuellenManagerProps {
  initialQuellen: any[]; // Firebase Quelle type
  initialKapitels: FirebaseKapitel[];
  projektId: string;
}

export function QuellenManager({ initialQuellen, initialKapitels, projektId }: QuellenManagerProps) {
  const router = useRouter();
  const [quellen, setQuellen] = useState<Quelle[]>(
    initialQuellen.map((q) => transformQuelleToUI(q, projektId))
  );
  const [kapitels] = useState(initialKapitels);

  // UI state
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedQuelleIds, setSelectedQuelleIds] = useState<Set<string>>(new Set());
  const [filterColor, setFilterColor] = useState<string | null>(null);
  const [filterType, setFilterType] = useState<string | null>(null);
  const [isUpdatingColor, setIsUpdatingColor] = useState(false);
  const [isBulkAssigning, setIsBulkAssigning] = useState(false);
  const [quelleKapitelMap, setQuelleKapitelMap] = useState<Map<string, string[]>>(new Map());

  // Load Kapitel memberships for each Quelle
  useEffect(() => {
    const map = new Map<string, string[]>();
    quellen.forEach((quelle) => {
      const kapitelIds = kapitels
        .filter((k) => k.quelleIds.includes(quelle.id))
        .map((k) => k.id);
      map.set(quelle.id, kapitelIds);
    });
    setQuelleKapitelMap(map);
  }, [quellen, kapitels]);

  // Filtered and grouped Quellen
  const filteredQuellen = useMemo(() => {
    let filtered = quellen;

    // Search filter
    if (searchQuery) {
      filtered = filtered.filter((q) =>
        q.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        q.autor?.toLowerCase().includes(searchQuery.toLowerCase())
      );
    }

    // Color filter
    if (filterColor) {
      filtered = filtered.filter((q) => q.color === filterColor);
    }

    // Type filter
    if (filterType) {
      filtered = filtered.filter((q) => q.typ === filterType);
    }

    return filtered;
  }, [quellen, searchQuery, filterColor, filterType]);

  // Group by color
  const groupedByColor = useMemo(() => {
    const groups = new Map<string, Quelle[]>();

    // Group with color
    QUELLE_COLORS.forEach((color) => {
      const colorQuellen = filteredQuellen.filter((q) => q.color === color);
      if (colorQuellen.length > 0) {
        groups.set(color, colorQuellen);
      }
    });

    // Group without color
    const noColorQuellen = filteredQuellen.filter((q) => !q.color);
    if (noColorQuellen.length > 0) {
      groups.set('no-color', noColorQuellen);
    }

    return groups;
  }, [filteredQuellen]);

  // Selection handlers
  const handleToggleSelection = (quelleId: string) => {
    setSelectedQuelleIds((prev) => {
      const next = new Set(prev);
      if (next.has(quelleId)) {
        next.delete(quelleId);
      } else {
        next.add(quelleId);
      }
      return next;
    });
  };

  const handleSelectAll = () => {
    if (selectedQuelleIds.size === filteredQuellen.length) {
      setSelectedQuelleIds(new Set());
    } else {
      setSelectedQuelleIds(new Set(filteredQuellen.map((q) => q.id)));
    }
  };

  // Color update handler
  const handleUpdateColor = async (quelleId: string, color: string | null) => {
    setIsUpdatingColor(true);
    try {
      const result = await updateQuelleColor(quelleId, color as any);
      if (result.success) {
        setQuellen((prev) =>
          prev.map((q) =>
            q.id === quelleId ? { ...q, color: color as any } : q
          )
        );
        toast.success('Farbe aktualisiert');
      } else {
        toast.error('Fehler beim Aktualisieren der Farbe');
      }
    } catch (error) {
      toast.error('Fehler beim Aktualisieren der Farbe');
    } finally {
      setIsUpdatingColor(false);
    }
  };

  // Bulk assignment handler
  const handleBulkAssign = async (kapitelId: string) => {
    if (selectedQuelleIds.size === 0) return;

    setIsBulkAssigning(true);
    try {
      const result = await bulkAssignQuellen(
        Array.from(selectedQuelleIds),
        [kapitelId],
        projektId
      );
      if (result.success) {
        toast.success(`${selectedQuelleIds.size} Quellen zugewiesen`);
        setSelectedQuelleIds(new Set());
        // Refresh Kapitel memberships
        router.refresh();
      } else {
        toast.error('Fehler beim Zuweisen');
      }
    } catch (error) {
      toast.error('Fehler beim Zuweisen');
    } finally {
      setIsBulkAssigning(false);
    }
  };

  return (
    <div className="min-h-screen bg-background p-8">
      {/* Header */}
      <div className="max-w-7xl mx-auto mb-8">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-4">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => router.push('/dashboard')}
            >
              <ArrowLeft className="h-4 w-4 mr-2" />
              Zurück
            </Button>
            <div>
              <h1 className="text-3xl font-bold">Quellen-Manager</h1>
              <p className="text-muted-foreground">
                Verwalte alle Quellen für dieses Projekt
              </p>
            </div>
          </div>
          <Button onClick={() => router.push('/dashboard')}>
            <Plus className="h-4 w-4 mr-2" />
            Neue Quelle
          </Button>
        </div>

        {/* Filters and Search */}
        <div className="flex items-center gap-4 flex-wrap">
          <div className="relative flex-1 min-w-[300px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Quellen durchsuchen..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9"
            />
          </div>

          <Select value={filterColor || 'all'} onValueChange={(val) => setFilterColor(val === 'all' ? null : val)}>
            <SelectTrigger className="w-[180px]">
              <SelectValue placeholder="Farbe filtern" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Alle Farben</SelectItem>
              {QUELLE_COLORS.map((color) => (
                <SelectItem key={color} value={color}>
                  <div className="flex items-center gap-2">
                    <div className={cn("w-3 h-3 rounded-full", COLOR_CLASSES[color].split(' ')[0])} />
                    {color}
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={filterType || 'all'} onValueChange={(val) => setFilterType(val === 'all' ? null : val)}>
            <SelectTrigger className="w-[180px]">
              <SelectValue placeholder="Typ filtern" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Alle Typen</SelectItem>
              {QUELLE_TYPES.map((type) => (
                <SelectItem key={type} value={type}>
                  {type}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Bulk actions */}
        {selectedQuelleIds.size > 0 && (
          <Card className="mt-4 p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <p className="text-sm font-medium">
                  {selectedQuelleIds.size} Quelle(n) ausgewählt
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setSelectedQuelleIds(new Set())}
                >
                  Auswahl aufheben
                </Button>
              </div>
              <Select onValueChange={handleBulkAssign} disabled={isBulkAssigning}>
                <SelectTrigger className="w-[250px]">
                  <SelectValue placeholder="Zu Kapitel hinzufügen..." />
                </SelectTrigger>
                <SelectContent>
                  {kapitels.map((kapitel) => (
                    <SelectItem key={kapitel.id} value={kapitel.id}>
                      {kapitel.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </Card>
        )}
      </div>

      {/* Quellen Table/Grid */}
      <div className="max-w-7xl mx-auto">
        <div className="mb-4 flex items-center justify-between">
          <p className="text-sm text-muted-foreground">
            {filteredQuellen.length} Quelle(n)
          </p>
          <Button variant="ghost" size="sm" onClick={handleSelectAll}>
            {selectedQuelleIds.size === filteredQuellen.length ? 'Alle abwählen' : 'Alle auswählen'}
          </Button>
        </div>

        {/* Color groups */}
        {Array.from(groupedByColor.entries()).map(([colorKey, colorQuellen]) => (
          <div key={colorKey} className="mb-8">
            <div className="flex items-center gap-2 mb-3">
              {colorKey !== 'no-color' ? (
                <>
                  <div className={cn("w-3 h-3 rounded-full", COLOR_CLASSES[colorKey as QuelleColor].split(' ')[0])} />
                  <h2 className="text-lg font-semibold">{colorKey} ({colorQuellen.length})</h2>
                </>
              ) : (
                <h2 className="text-lg font-semibold text-muted-foreground">
                  Ohne Farbe ({colorQuellen.length})
                </h2>
              )}
            </div>

            {/* Table */}
            <Card className="overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-muted/50 border-b">
                    <tr>
                      <th className="w-12 p-3 text-left">
                        <Checkbox
                          checked={colorQuellen.every((q) => selectedQuelleIds.has(q.id))}
                          onCheckedChange={() => {
                            const allSelected = colorQuellen.every((q) => selectedQuelleIds.has(q.id));
                            setSelectedQuelleIds((prev) => {
                              const next = new Set(prev);
                              colorQuellen.forEach((q) => {
                                if (allSelected) {
                                  next.delete(q.id);
                                } else {
                                  next.add(q.id);
                                }
                              });
                              return next;
                            });
                          }}
                        />
                      </th>
                      <th className="p-3 text-left text-sm font-medium">Name</th>
                      <th className="p-3 text-left text-sm font-medium">Autor</th>
                      <th className="p-3 text-left text-sm font-medium">Jahr</th>
                      <th className="p-3 text-left text-sm font-medium">Typ</th>
                      <th className="p-3 text-left text-sm font-medium">Wörter</th>
                      <th className="p-3 text-left text-sm font-medium">Kapitels</th>
                      <th className="p-3 text-left text-sm font-medium">Farbe</th>
                    </tr>
                  </thead>
                  <tbody>
                    {colorQuellen.map((quelle) => (
                      <tr
                        key={quelle.id}
                        className={cn(
                          "border-b hover:bg-muted/30 transition-colors",
                          selectedQuelleIds.has(quelle.id) && "bg-muted/50"
                        )}
                      >
                        <td className="p-3">
                          <Checkbox
                            checked={selectedQuelleIds.has(quelle.id)}
                            onCheckedChange={() => handleToggleSelection(quelle.id)}
                          />
                        </td>
                        <td className="p-3">
                          <div className="flex items-center gap-2">
                            <BookOpen className="h-4 w-4 text-muted-foreground shrink-0" />
                            <span className="font-medium">{quelle.name}</span>
                          </div>
                        </td>
                        <td className="p-3 text-sm text-muted-foreground">
                          {quelle.autor || '-'}
                        </td>
                        <td className="p-3 text-sm text-muted-foreground">
                          {quelle.jahr || '-'}
                        </td>
                        <td className="p-3">
                          {quelle.typ ? (
                            <Badge variant="secondary">{quelle.typ}</Badge>
                          ) : (
                            <span className="text-sm text-muted-foreground">-</span>
                          )}
                        </td>
                        <td className="p-3 text-sm text-muted-foreground">
                          {quelle.text.split(/\s+/).filter(Boolean).length}
                        </td>
                        <td className="p-3">
                          <div className="flex flex-wrap gap-1">
                            {quelleKapitelMap.get(quelle.id)?.map((kId) => {
                              const kapitel = kapitels.find((k) => k.id === kId);
                              return kapitel ? (
                                <Badge key={kId} variant="outline" className="text-xs">
                                  {kapitel.title}
                                </Badge>
                              ) : null;
                            })}
                            {(!quelleKapitelMap.get(quelle.id) || quelleKapitelMap.get(quelle.id)!.length === 0) && (
                              <span className="text-xs text-muted-foreground">Keine</span>
                            )}
                          </div>
                        </td>
                        <td className="p-3">
                          <Popover>
                            <PopoverTrigger asChild>
                              <Button variant="ghost" size="sm" className="h-8 w-8 p-0">
                                <Palette className="h-4 w-4" />
                              </Button>
                            </PopoverTrigger>
                            <PopoverContent className="w-48">
                              <div className="space-y-2">
                                <p className="text-xs font-medium mb-2">Farbe auswählen</p>
                                <div className="grid grid-cols-4 gap-2">
                                  {QUELLE_COLORS.map((color) => (
                                    <button
                                      key={color}
                                      className={cn(
                                        "w-8 h-8 rounded-full border-2 transition-all hover:scale-110",
                                        COLOR_CLASSES[color].split(' ')[0],
                                        quelle.color === color && "ring-2 ring-primary ring-offset-2"
                                      )}
                                      onClick={() => handleUpdateColor(quelle.id, color)}
                                    />
                                  ))}
                                </div>
                                {quelle.color && (
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="w-full mt-2"
                                    onClick={() => handleUpdateColor(quelle.id, null)}
                                  >
                                    Farbe entfernen
                                  </Button>
                                )}
                              </div>
                            </PopoverContent>
                          </Popover>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>
        ))}

        {filteredQuellen.length === 0 && (
          <Card className="p-12 text-center">
            <BookOpen className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
            <p className="text-lg font-medium mb-2">Keine Quellen gefunden</p>
            <p className="text-sm text-muted-foreground">
              {searchQuery || filterColor || filterType
                ? 'Versuche andere Filter'
                : 'Erstelle eine neue Quelle, um loszulegen'}
            </p>
          </Card>
        )}
      </div>
    </div>
  );
}
