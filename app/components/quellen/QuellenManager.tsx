'use client';

import { useState, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Search, Trash2, ChevronDown, ChevronUp, ArrowUpDown, FolderPlus, Eye, ArrowLeft, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';
import type { Quelle } from '@/app/types/ui';
import type { Kapitel as FirebaseKapitel } from '@/app/actions/kapitels';
import { transformQuelleToUI } from '@/app/lib/transformers/ui-data';
import { updateQuelleColor, bulkAssignQuellen, deleteQuelle } from '@/app/actions/quellen';
import { QUELLE_COLORS, colorMap, colorLabels, QUELLE_TYPES, type QuelleColor } from '@/app/lib/quellen/fieldConfig';
import { QuelleViewerModal } from '@/app/components/dashboard/QuelleViewerModal';

interface QuellenManagerProps {
  initialQuellen: any[];
  initialKapitels: FirebaseKapitel[];
  projektId: string;
}

type SortField = 'name' | 'typ' | 'jahr' | 'color';
type SortDirection = 'asc' | 'desc';

const typLabels: Record<string, string> = {
  'Book': 'Buch',
  'Article': 'Artikel',
  'Website': 'Website',
  'Thesis': 'Thesis',
  'Report': 'Report',
};

export function QuellenManager({ initialQuellen, initialKapitels, projektId }: QuellenManagerProps) {
  const router = useRouter();
  const [quellen, setQuellen] = useState<Quelle[]>(
    initialQuellen.map((q) => transformQuelleToUI(q, projektId))
  );
  const [kapitels] = useState(initialKapitels);

  const [searchQuery, setSearchQuery] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [sortField, setSortField] = useState<SortField>('name');
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');
  const [filterTyp, setFilterTyp] = useState<string | 'all'>('all');
  const [filterColor, setFilterColor] = useState<QuelleColor | 'all' | null>('all');
  const [assignDialogOpen, setAssignDialogOpen] = useState(false);
  const [selectedKapitelIds, setSelectedKapitelIds] = useState<Set<string>>(new Set());
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [viewingQuelle, setViewingQuelle] = useState<Quelle | null>(null);

  const filteredQuellen = useMemo(() => {
    let result = quellen.filter((q) => q.name.toLowerCase().includes(searchQuery.toLowerCase()));

    if (filterTyp !== 'all') {
      result = result.filter((q) => q.typ === filterTyp);
    }

    if (filterColor !== 'all') {
      result = result.filter((q) => q.color === filterColor);
    }

    result.sort((a, b) => {
      let comparison = 0;
      switch (sortField) {
        case 'name':
          comparison = a.name.localeCompare(b.name);
          break;
        case 'typ':
          comparison = (a.typ || '').localeCompare(b.typ || '');
          break;
        case 'jahr':
          comparison = (a.jahr || 0) - (b.jahr || 0);
          break;
        case 'color':
          comparison = (a.color || 'zzz').localeCompare(b.color || 'zzz');
          break;
      }
      return sortDirection === 'asc' ? comparison : -comparison;
    });

    return result;
  }, [quellen, searchQuery, filterTyp, filterColor, sortField, sortDirection]);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('asc');
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
    // If exactly one Quelle is selected, pre-select Kapitels that already have it
    if (selectedIds.size === 1) {
      const quelleId = Array.from(selectedIds)[0];
      const linkedKapitels = kapitels.filter((k) => k.quelleIds.includes(quelleId));
      setSelectedKapitelIds(new Set(linkedKapitels.map((k) => k.id)));
    } else {
      setSelectedKapitelIds(new Set());
    }
    setAssignDialogOpen(true);
  };

  const handleAssign = async () => {
    const count = selectedIds.size;
    const kapitelCount = selectedKapitelIds.size;

    try {
      await bulkAssignQuellen(
        Array.from(selectedIds),
        Array.from(selectedKapitelIds),
        projektId
      );
      toast.success(`${count} Quellen zu ${kapitelCount} Kapiteln zugewiesen`);
      setAssignDialogOpen(false);
      setSelectedKapitelIds(new Set());
      setSelectedIds(new Set());
      router.refresh();
    } catch (error) {
      toast.error('Fehler beim Zuweisen der Quellen');
    }
  };

  const handleColorChange = async (quelleId: string, color: QuelleColor | null) => {
    // Optimistic update - update UI immediately
    setQuellen((prev) => prev.map((q) => (q.id === quelleId ? { ...q, color } : q)));

    try {
      await updateQuelleColor(quelleId, color);
    } catch (error) {
      // Revert on error by refreshing
      router.refresh();
    }
  };

  const handleDelete = async () => {
    const quelleId = Array.from(selectedIds)[0];
    try {
      await deleteQuelle(quelleId);
      setQuellen((prev) => prev.filter((q) => q.id !== quelleId));
      setSelectedIds(new Set());
      setDeleteConfirmOpen(false);
      toast.success('Quelle gelöscht');
      router.refresh();
    } catch (error) {
      toast.error('Fehler beim Löschen der Quelle');
    }
  };

  const getLinkedKapiteln = (quelleId: string) => {
    return kapitels.filter((k) => k.quelleIds.includes(quelleId));
  };

  const sortedKapiteln = useMemo(() => {
    return [...kapitels].sort((a, b) => {
      if (!a.nummer || !b.nummer) return 0;
      const partsA = a.nummer.split('.').map(Number);
      const partsB = b.nummer.split('.').map(Number);
      for (let i = 0; i < Math.max(partsA.length, partsB.length); i++) {
        const numA = partsA[i] || 0;
        const numB = partsB[i] || 0;
        if (numA !== numB) return numA - numB;
      }
      return 0;
    });
  }, [kapitels]);

  const SortButton = ({ field, children }: { field: SortField; children: React.ReactNode }) => (
    <Button
      variant="ghost"
      size="sm"
      className="h-8 px-2 -ml-2 font-medium hover:bg-muted/50"
      onClick={() => handleSort(field)}
    >
      {children}
      {sortField === field ? (
        sortDirection === 'asc' ? (
          <ChevronUp className="ml-1 h-4 w-4" />
        ) : (
          <ChevronDown className="ml-1 h-4 w-4" />
        )
      ) : (
        <ArrowUpDown className="ml-1 h-4 w-4 opacity-30" />
      )}
    </Button>
  );

  return (
    <>
      <div className="min-h-screen bg-background flex flex-col">
        {/* Header */}
        <div className="border-b border-border px-6 py-4 flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => router.push('/dashboard')}>
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <div>
            <h1 className="text-xl font-semibold">Quellen-Manager</h1>
            <p className="text-sm text-muted-foreground">{quellen.length} Quellen</p>
          </div>
        </div>

        {/* Toolbar */}
        <div className="border-b border-border px-6 py-3 flex items-center gap-4 flex-wrap">
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
                Typ: {filterTyp === 'all' ? 'Alle' : typLabels[filterTyp] || filterTyp}
                <ChevronDown className="ml-2 h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuItem onClick={() => setFilterTyp('all')}>Alle</DropdownMenuItem>
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
                    backgroundColor: filterColor && filterColor !== 'all' ? colorMap[filterColor] : 'var(--muted)',
                    border: filterColor === 'all' || !filterColor ? '1px solid var(--border)' : undefined,
                  }}
                />
                Farbe
                <ChevronDown className="ml-2 h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuItem onClick={() => setFilterColor('all')}>Alle Farben</DropdownMenuItem>
              {QUELLE_COLORS.map((color) => (
                <DropdownMenuItem key={color} onClick={() => setFilterColor(color)}>
                  <span className="w-4 h-4 rounded mr-2" style={{ backgroundColor: colorMap[color] }} />
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

          {selectedIds.size > 0 && (
            <div className="flex items-center gap-2">
              <Badge variant="secondary" className="px-3 py-1">
                {selectedIds.size} ausgewählt
              </Badge>
              {selectedIds.size === 1 && (
                <>
                  <Button size="sm" variant="outline" onClick={openAssignDialog}>
                    <FolderPlus className="h-4 w-4 mr-2" />
                    Zu Kapitel
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setDeleteConfirmOpen(true)}>
                    <Trash2 className="h-4 w-4 mr-2" />
                    Löschen
                  </Button>
                </>
              )}
            </div>
          )}
        </div>

        <div className="flex-1 overflow-auto px-6 py-4">
          <Card>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">
                    <Checkbox
                      checked={filteredQuellen.length > 0 && selectedIds.size === filteredQuellen.length}
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
                  <TableHead className="w-20">
                    <SortButton field="jahr">Jahr</SortButton>
                  </TableHead>
                  <TableHead className="w-40">Kapitel</TableHead>
                  <TableHead className="w-20 text-right">Aktionen</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredQuellen.map((quelle) => {
                  const linkedKapiteln = getLinkedKapiteln(quelle.id);
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
                                backgroundColor: quelle.color ? colorMap[quelle.color] : 'var(--background)',
                                borderColor: quelle.color ? colorMap[quelle.color] : 'var(--border)',
                              }}
                            />
                          </DropdownMenuTrigger>
                          <DropdownMenuContent>
                            {QUELLE_COLORS.map((color) => (
                              <DropdownMenuItem
                                key={color}
                                onClick={() => handleColorChange(quelle.id, color)}
                                className="flex items-center gap-2"
                              >
                                <span className="w-4 h-4 rounded" style={{ backgroundColor: colorMap[color] }} />
                                {colorLabels[color]}
                                {quelle.color === color && <Check className="h-3 w-3 ml-auto" />}
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
                      <TableCell>
                        <div className="font-medium truncate max-w-[300px]">{quelle.name}</div>
                        {quelle.autor && <div className="text-xs text-muted-foreground">{quelle.autor}</div>}
                      </TableCell>
                      <TableCell className="text-muted-foreground text-sm">
                        {quelle.typ ? typLabels[quelle.typ] || quelle.typ : '-'}
                      </TableCell>
                      <TableCell className="text-muted-foreground">{quelle.jahr || '-'}</TableCell>
                      <TableCell>
                        {linkedKapiteln.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {linkedKapiteln.slice(0, 2).map((k) => (
                              <Badge key={k.id} variant="outline" className="text-xs px-1.5 py-0">
                                {k.nummer}
                              </Badge>
                            ))}
                            {linkedKapiteln.length > 2 && (
                              <span className="text-xs text-muted-foreground">+{linkedKapiteln.length - 2}</span>
                            )}
                          </div>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          onClick={() => setViewingQuelle(quelle)}
                        >
                          <Eye className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
                {filteredQuellen.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={7} className="h-24 text-center text-muted-foreground">
                      Keine Quellen gefunden
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </Card>
        </div>
      </div>

      {/* Assign Dialog */}
      <Dialog open={assignDialogOpen} onOpenChange={setAssignDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Zu Kapiteln zuweisen</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <p className="text-sm text-muted-foreground mb-4">
              {selectedIds.size} Quelle(n) zu folgenden Kapiteln zuweisen:
            </p>
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {sortedKapiteln.map((kapitel) => {
                const depth = kapitel.nummer ? kapitel.nummer.split('.').length - 1 : 0;
                return (
                  <div
                    key={kapitel.id}
                    className={cn(
                      'flex items-center gap-3 p-2 rounded hover:bg-muted/50 cursor-pointer',
                      selectedKapitelIds.has(kapitel.id) && 'bg-muted'
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
                    <span className="text-sm font-medium">{kapitel.nummer || ''}</span>
                    <span className="text-sm text-muted-foreground truncate">{kapitel.title}</span>
                  </div>
                );
              })}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAssignDialogOpen(false)}>
              Abbrechen
            </Button>
            <Button onClick={handleAssign} disabled={selectedKapitelIds.size === 0}>
              Zuweisen
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteConfirmOpen} onOpenChange={setDeleteConfirmOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Quelle löschen</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <p className="text-sm text-muted-foreground">
              Möchten Sie diese Quelle wirklich löschen? Diese Aktion kann nicht rückgängig gemacht werden.
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteConfirmOpen(false)}>
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
        open={viewingQuelle !== null}
        onOpenChange={(open) => !open && setViewingQuelle(null)}
      />
    </>
  );
}
