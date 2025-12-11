"use client"

import type React from "react"

import { useState, useEffect } from "react"
import Link from "next/link"
import { ArrowLeft, Mail, Calendar, FileText, BookOpen, Coins, BarChart3, Zap, PenTool } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Input } from "@/components/ui/input"
import { toast } from "sonner"
import Cookies from "js-cookie"
import { useAuth } from "@/app/components/providers/AuthProvider"
import { deleteOpenAIKey, fetchOpenAIKeyStatus, saveOpenAIKey, type OpenAIKeyStatus } from "@/app/lib/api/openaiKeyClient"

// Mock data - will be replaced with real Firebase data later
const mockUser = {
  id: "1",
  name: "Max Mustermann",
  email: "max.mustermann@example.com",
  memberSince: new Date("2024-01-15"),
}

const mockUserStats = {
  totalCost: 1247, // in cents
  totalRuns: 23,
  totalProjekte: 3,
  totalKapitel: 12,
  totalQuellen: 45,
  totalWords: 87450,
  runsByMonth: [
    { month: "Januar", runs: 5, cost: 245 },
    { month: "Februar", runs: 8, cost: 412 },
    { month: "März", runs: 10, cost: 590 },
  ],
  costByProjekt: [
    { projektName: "Masterarbeit", cost: 847 },
    { projektName: "Bachelorarbeit", cost: 280 },
    { projektName: "Seminararbeit", cost: 120 },
  ],
  modelUsage: [
    { model: "gpt-5-nano", count: 18 },
    { model: "gpt-5-mini", count: 4 },
    { model: "gpt-5.1", count: 1 },
  ],
  memberSince: new Date("2024-01-15"),
}

function StatCard({
  icon: Icon,
  label,
  value,
  subtext,
}: {
  icon: React.ElementType
  label: string
  value: string
  subtext?: string
}) {
  return (
    <Card className="p-5">
      <div className="flex items-start gap-4">
        <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
          <Icon className="h-5 w-5 text-primary" />
        </div>
        <div className="min-w-0">
          <p className="text-sm text-muted-foreground">{label}</p>
          <p className="text-2xl font-semibold text-foreground mt-1">{value}</p>
          {subtext && <p className="text-xs text-muted-foreground mt-1">{subtext}</p>}
        </div>
      </div>
    </Card>
  )
}

function StatCardSkeleton() {
  return (
    <Card className="p-5">
      <div className="flex items-start gap-4">
        <Skeleton className="w-10 h-10 rounded-lg" />
        <div className="flex-1">
          <Skeleton className="h-4 w-20 mb-2" />
          <Skeleton className="h-8 w-24" />
        </div>
      </div>
    </Card>
  )
}

function ProfilePageSkeleton() {
  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-5xl mx-auto py-12 px-8">
        {/* Header skeleton */}
        <div className="flex items-center gap-3 mb-10">
          <Skeleton className="h-9 w-9 rounded-md" />
          <Skeleton className="h-8 w-48" />
        </div>

        {/* Profile card skeleton */}
        <Card className="p-8 mb-10">
          <div className="flex items-start gap-6">
            <Skeleton className="w-20 h-20 rounded-full" />
            <div className="flex-1">
              <Skeleton className="h-7 w-48 mb-2" />
              <Skeleton className="h-4 w-64 mb-4" />
              <div className="flex gap-4">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-4 w-40" />
              </div>
            </div>
          </div>
        </Card>

        {/* Stats grid skeleton */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-10">
          {[...Array(4)].map((_, i) => (
            <StatCardSkeleton key={i} />
          ))}
        </div>

        {/* Charts section skeleton */}
        <div className="grid md:grid-cols-2 gap-6">
          <Card className="p-6">
            <Skeleton className="h-5 w-40 mb-6" />
            <div className="space-y-3">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="flex items-center gap-3">
                  <Skeleton className="h-4 w-16" />
                  <Skeleton className="h-6 flex-1 rounded" />
                  <Skeleton className="h-4 w-12" />
                </div>
              ))}
            </div>
          </Card>
          <Card className="p-6">
            <Skeleton className="h-5 w-40 mb-6" />
            <div className="space-y-3">
              {[...Array(3)].map((_, i) => (
                <div key={i} className="flex items-center gap-3">
                  <Skeleton className="h-4 w-48" />
                  <Skeleton className="h-4 flex-1" />
                  <Skeleton className="h-4 w-16" />
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}

export default function ProfilPage() {
  const { user: authUser, loading: authLoading } = useAuth()
  const [stats] = useState<typeof mockUserStats | null>(mockUserStats)
  const [keyStatus, setKeyStatus] = useState<OpenAIKeyStatus | null>(null)
  const [keyLoading, setKeyLoading] = useState(true)
  const [savingKey, setSavingKey] = useState(false)
  const [apiKeyInput, setApiKeyInput] = useState("")
  const [statusError, setStatusError] = useState<string | null>(null)

  useEffect(() => {
    if (authLoading) return
    const token = Cookies.get("__session")
    if (!token) {
      setStatusError("Keine Sitzung gefunden. Bitte melde dich erneut an.")
      setKeyLoading(false)
      return
    }

    fetchOpenAIKeyStatus(token)
      .then(setKeyStatus)
      .catch((err: any) => {
        const message = err?.message || "OpenAI-Schlüsselstatus konnte nicht geladen werden."
        setStatusError(message)
        toast.error("OpenAI Key", { description: message })
      })
      .finally(() => setKeyLoading(false))
  }, [authLoading, authUser?.uid])

  const handleSaveKey = async () => {
    if (!apiKeyInput.trim()) return
    const token = Cookies.get("__session")
    if (!token) {
      toast.error("Sitzung abgelaufen", { description: "Bitte melde dich erneut an." })
      return
    }
    try {
      setSavingKey(true)
      const status = await saveOpenAIKey(token, apiKeyInput.trim())
      setKeyStatus(status)
      setApiKeyInput("")
      toast.success("OpenAI Key gespeichert")
    } catch (err: any) {
      const message = err?.message || "Key konnte nicht gespeichert werden."
      toast.error("Fehler", { description: message })
    } finally {
      setSavingKey(false)
    }
  }

  const handleDeleteKey = async () => {
    const token = Cookies.get("__session")
    if (!token) {
      toast.error("Sitzung abgelaufen", { description: "Bitte melde dich erneut an." })
      return
    }
    try {
      setSavingKey(true)
      const status = await deleteOpenAIKey(token)
      setKeyStatus(status)
      toast.success("OpenAI Key entfernt")
    } catch (err: any) {
      const message = err?.message || "Key konnte nicht entfernt werden."
      toast.error("Fehler", { description: message })
    } finally {
      setSavingKey(false)
    }
  }

  const isLoading = authLoading || keyLoading || !authUser

  if (isLoading || !stats) {
    return <ProfilePageSkeleton />
  }

  const userName = authUser?.displayName || authUser?.email || mockUser.name
  const userEmail = authUser?.email || mockUser.email
  const memberSince = stats.memberSince

  const formatCost = (cents: number) => `${(cents / 100).toFixed(2)} €`
  const formatNumber = (num: number) => num.toLocaleString("de-DE")

  const initials = userName
    .split(" ")
    .map((n) => n[0])
    .join("")
    .toUpperCase()
    .slice(0, 2)

  const maxMonthlyRuns = Math.max(...stats.runsByMonth.map((m) => m.runs))
  const maxProjektCost = Math.max(...stats.costByProjekt.map((p) => p.cost))

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-5xl mx-auto py-12 px-8">
        {/* Header */}
        <div className="flex items-center gap-3 mb-10">
          <Link href="/dashboard">
            <Button variant="ghost" size="icon" className="h-9 w-9">
              <ArrowLeft className="h-5 w-5" />
            </Button>
          </Link>
          <h1 className="text-2xl font-semibold text-foreground">Dein Profil</h1>
        </div>

        {/* Profile Card */}
        <Card className="p-8 mb-10">
          <div className="flex items-start gap-6">
            <div className="w-20 h-20 rounded-full bg-primary/10 flex items-center justify-center text-2xl font-semibold text-primary shrink-0">
              {initials}
            </div>
            <div className="flex-1 min-w-0">
              <h2 className="text-xl font-semibold text-foreground">{userName}</h2>
              <div className="flex items-center gap-2 mt-1 text-muted-foreground">
                <Mail className="h-4 w-4" />
                <span className="text-sm">{userEmail}</span>
              </div>
              <div className="flex items-center gap-4 mt-4 text-sm text-muted-foreground">
                <div className="flex items-center gap-1.5">
                  <Calendar className="h-4 w-4" />
                  <span>
                    Mitglied seit {memberSince.toLocaleDateString("de-DE", { month: "long", year: "numeric" })}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </Card>

        {/* OpenAI Key Management */}
        <Card className="p-6 mb-10">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="space-y-2">
              <h3 className="text-lg font-semibold text-foreground">OpenAI API Key</h3>
              <p className="text-sm text-muted-foreground">
                Dein Key wird serverseitig validiert und verschlüsselt gespeichert. Ohne eigenen Key können keine
                Verarbeitungen gestartet werden (außer du bist für den Plattform-Key freigeschaltet).
              </p>
              <div className="text-sm">
                <span className="font-medium">Status: </span>
                {keyStatus
                  ? keyStatus.hasKey
                    ? `Eigener Key aktiv${keyStatus.last4 ? ` (****${keyStatus.last4})` : ""}`
                    : keyStatus.allowPlatformKey
                      ? "Plattform-Key wird verwendet, solange kein eigener Key hinterlegt ist."
                      : "Kein Key hinterlegt."
                  : "Status konnte nicht geladen werden."}
              </div>
              {statusError && <p className="text-sm text-destructive">{statusError}</p>}
            </div>
            <div className="w-full sm:w-96 space-y-3">
              <Input
                type="password"
                placeholder="sk-..."
                value={apiKeyInput}
                onChange={(e) => setApiKeyInput(e.target.value)}
                disabled={savingKey}
              />
              <div className="flex gap-2">
                <Button onClick={handleSaveKey} disabled={!apiKeyInput.trim() || savingKey}>
                  Key speichern
                </Button>
                {keyStatus?.hasKey && (
                  <Button variant="outline" onClick={handleDeleteKey} disabled={savingKey}>
                    Key entfernen
                  </Button>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                Hinweis: Der Key wird nicht im Browser angezeigt. Speichere ihn sicher für spätere Updates.
              </p>
            </div>
          </div>
        </Card>

        {/* Quick Stats */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-10">
          <StatCard
            icon={Coins}
            label="Gesamtkosten"
            value={formatCost(stats.totalCost)}
            subtext={`${stats.totalRuns} Verarbeitungen`}
          />
          <StatCard
            icon={FileText}
            label="Projekte"
            value={String(stats.totalProjekte)}
            subtext={`${stats.totalKapitel} Kapitel`}
          />
          <StatCard icon={BookOpen} label="Quellen" value={String(stats.totalQuellen)} subtext="Hochgeladen" />
          <StatCard
            icon={PenTool}
            label="Generierte Wörter"
            value={formatNumber(stats.totalWords)}
            subtext="Insgesamt"
          />
        </div>

        {/* Detailed Stats */}
        <div className="grid md:grid-cols-2 gap-6 mb-10">
          {/* Monthly Activity */}
          <Card className="p-6">
            <h3 className="text-sm font-medium text-foreground mb-6 flex items-center gap-2">
              <BarChart3 className="h-4 w-4 text-muted-foreground" />
              Aktivität pro Monat
            </h3>
            <div className="space-y-4">
              {stats.runsByMonth.map((month) => (
                <div key={month.month} className="flex items-center gap-3">
                  <span className="text-sm text-muted-foreground w-20 shrink-0">{month.month.slice(0, 3)}</span>
                  <div className="flex-1 h-6 bg-muted/30 rounded overflow-hidden">
                    <div
                      className="h-full bg-primary/70 rounded transition-all"
                      style={{ width: `${(month.runs / maxMonthlyRuns) * 100}%` }}
                    />
                  </div>
                  <span className="text-sm text-muted-foreground w-16 text-right">{month.runs} Runs</span>
                </div>
              ))}
            </div>
          </Card>

          {/* Cost by Project */}
          <Card className="p-6">
            <h3 className="text-sm font-medium text-foreground mb-6 flex items-center gap-2">
              <Coins className="h-4 w-4 text-muted-foreground" />
              Kosten pro Projekt
            </h3>
            <div className="space-y-4">
              {stats.costByProjekt.map((projekt) => (
                <div key={projekt.projektName}>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-sm text-foreground truncate max-w-[200px]">{projekt.projektName}</span>
                    <span className="text-sm font-medium text-foreground">{formatCost(projekt.cost)}</span>
                  </div>
                  <div className="h-2 bg-muted/30 rounded overflow-hidden">
                    <div
                      className="h-full bg-primary/70 rounded transition-all"
                      style={{ width: `${(projekt.cost / maxProjektCost) * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>

        {/* Model Usage */}
        <Card className="p-6">
          <h3 className="text-sm font-medium text-foreground mb-6 flex items-center gap-2">
            <Zap className="h-4 w-4 text-muted-foreground" />
            Modellnutzung
          </h3>
          <div className="flex gap-6 flex-wrap">
            {stats.modelUsage.map((model) => (
              <div key={model.model} className="flex items-center gap-3 px-4 py-3 bg-muted/30 rounded-lg">
                <div className="w-3 h-3 rounded-full bg-primary" />
                <div>
                  <p className="text-sm font-medium text-foreground">{model.model}</p>
                  <p className="text-xs text-muted-foreground">{model.count} Verarbeitungen</p>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
