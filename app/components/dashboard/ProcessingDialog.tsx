"use client"

import { useState } from "react"
import { Play, Sparkles, Settings2, FileText, Wand2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Switch } from "@/components/ui/switch"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import type { ProcessingSettings } from "@/app/types/ui"

interface ProcessingDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  kapitelTitle: string
  quellenCount: number
  onProcess: (settings: ProcessingSettings) => void
}

export function ProcessingDialog({ open, onOpenChange, kapitelTitle, quellenCount, onProcess }: ProcessingDialogProps) {
  const [settings, setSettings] = useState<ProcessingSettings>({
    model: "gpt-5-nano",
    ueberschrift: kapitelTitle,
    thema: "",
    grundlegendeInfos: "",
    directCombine: true,
  })

  const handleProcess = () => {
    onProcess(settings)
  }

  const handleOpenChange = (open: boolean) => {
    if (open) {
      setSettings({
        model: "gpt-5-nano",
        ueberschrift: kapitelTitle,
        thema: "",
        grundlegendeInfos: "",
        directCombine: true,
      })
    }
    onOpenChange(open)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-xl [&>button]:hidden">
        <DialogHeader className="pb-4 border-b">
          <DialogTitle className="flex items-center gap-2 text-lg">
            <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
              <Sparkles className="h-4 w-4 text-primary" />
            </div>
            Kapitel verarbeiten
          </DialogTitle>
          <DialogDescription className="pt-1">{quellenCount} Quellen zugewiesen</DialogDescription>
        </DialogHeader>

        <div className="py-5 space-y-6">
          {/* Section 1: Kapitel Info */}
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <FileText className="h-4 w-4" />
              Kapitelinformationen
            </div>

            <div className="grid gap-4 pl-6">
              <div>
                <Label htmlFor="ueberschrift" className="text-sm">
                  Ueberschrift
                </Label>
                <Input
                  id="ueberschrift"
                  value={settings.ueberschrift}
                  onChange={(e) => setSettings({ ...settings, ueberschrift: e.target.value })}
                  placeholder="z.B. Einleitung"
                  className="mt-1.5"
                />
              </div>

              <div>
                <Label htmlFor="thema" className="text-sm">
                  Thema & Anweisungen
                </Label>
                <Textarea
                  id="thema"
                  value={settings.thema}
                  onChange={(e) => setSettings({ ...settings, thema: e.target.value })}
                  placeholder="Beschreibe, worum es in diesem Kapitel gehen soll und gib spezifische Anweisungen..."
                  className="mt-1.5 min-h-[80px] resize-none"
                />
              </div>

              <div>
                <Label htmlFor="grundlegende-infos" className="text-sm">
                  Grundlegende Informationen
                  <span className="text-muted-foreground font-normal ml-1">(optional)</span>
                </Label>
                <Textarea
                  id="grundlegende-infos"
                  value={settings.grundlegendeInfos}
                  onChange={(e) => setSettings({ ...settings, grundlegendeInfos: e.target.value })}
                  placeholder="Hintergrundinformationen, Kontext oder zusaetzliche Details, die bei der Verarbeitung beruecksichtigt werden sollen..."
                  className="mt-1.5 min-h-[70px] resize-none"
                />
              </div>
            </div>
          </div>

          {/* Section 2: Processing Settings */}
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <Settings2 className="h-4 w-4" />
              Verarbeitungseinstellungen
            </div>

            <div className="grid gap-4 pl-6">
              <div>
                <Label htmlFor="model" className="text-sm">
                  KI-Modell
                </Label>
                <Select
                  value={settings.model}
                  onValueChange={(value) => setSettings({ ...settings, model: value as ProcessingSettings["model"] })}
                >
                  <SelectTrigger className="mt-1.5">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="gpt-5-nano">
                      <div className="flex items-center justify-between w-full gap-4">
                        <span>GPT-5 nano</span>
                        <span className="text-xs text-muted-foreground">Empfohlen</span>
                      </div>
                    </SelectItem>
                    <SelectItem value="gpt-5-mini">
                      <div className="flex items-center justify-between w-full gap-4">
                        <span>GPT-5 mini</span>
                        <span className="text-xs text-muted-foreground">Beste Qualitaet</span>
                      </div>
                    </SelectItem>
                    <SelectItem value="gpt-5.1">
                      <div className="flex items-center justify-between w-full gap-4">
                        <span>GPT-5.1</span>
                        <span className="text-xs text-muted-foreground">Beste Qualitaet</span>
                      </div>
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="flex items-center justify-between py-3 px-4 bg-muted/40 rounded-lg">
                <div className="flex items-center gap-3">
                  <Wand2 className="h-4 w-4 text-muted-foreground" />
                  <div>
                    <Label htmlFor="direct-combine" className="text-sm font-medium cursor-pointer">
                      Direkt kombinieren
                    </Label>
                    <p className="text-xs text-muted-foreground mt-0.5">Erstellt sofort einen zusammenhaengenden Text</p>
                  </div>
                </div>
                <Switch
                  id="direct-combine"
                  checked={settings.directCombine}
                  onCheckedChange={(checked) => setSettings({ ...settings, directCombine: checked })}
                />
              </div>
            </div>
          </div>
        </div>

        <DialogFooter className="pt-4 border-t gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Abbrechen
          </Button>
          <Button onClick={handleProcess} disabled={quellenCount === 0 || !settings.ueberschrift.trim()}>
            <Play className="h-4 w-4 mr-2" />
            Verarbeitung starten
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
