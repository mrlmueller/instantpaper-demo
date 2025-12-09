"use client"

import { Copy, Check, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useState } from "react"

interface TextViewerModalProps {
  content: { title: string; text: string } | null
  onClose: () => void
}

export function TextViewerModal({ content, onClose }: TextViewerModalProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    if (content) {
      await navigator.clipboard.writeText(content.text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const wordCount = content?.text.split(/\s+/).filter(Boolean).length || 0

  return (
    <Dialog open={content !== null} onOpenChange={() => onClose()}>
      <DialogContent className="sm:max-w-4xl max-h-[90vh] flex flex-col [&>button]:hidden">
        <DialogHeader className="flex-shrink-0 pr-0">
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0 pr-2">
              <DialogTitle className="text-xl leading-tight text-balance">{content?.title}</DialogTitle>
              <div className="text-sm text-muted-foreground mt-1">{wordCount.toLocaleString("de-DE")} Wörter</div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <Button variant="outline" size="sm" onClick={handleCopy}>
                {copied ? (
                  <>
                    <Check className="h-4 w-4 mr-2 text-primary" />
                    Kopiert
                  </>
                ) : (
                  <>
                    <Copy className="h-4 w-4 mr-2" />
                    Kopieren
                  </>
                )}
              </Button>
              <Button variant="ghost" size="sm" onClick={onClose} className="h-8 w-8 p-0">
                <X className="h-4 w-4" />
                <span className="sr-only">Schließen</span>
              </Button>
            </div>
          </div>
        </DialogHeader>
        <div className="flex-1 overflow-y-auto mt-4 pr-2">
          <div className="text-foreground/90 leading-relaxed whitespace-pre-wrap text-sm">{content?.text}</div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
