import { Skeleton } from "@/components/ui/skeleton"
import { Card } from "@/components/ui/card"
import { QuellenPanelSkeleton } from "./QuellenPanelSkeleton"

type DashboardSkeletonProps = {
  showQuellenPanel?: boolean
}

export function DashboardSkeleton({ showQuellenPanel = false }: DashboardSkeletonProps) {
  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Left Navigator Skeleton */}
      <div className="w-64 border-r border-border bg-sidebar flex flex-col">
        {/* Header skeleton */}
        <div className="p-4 border-b border-sidebar-border">
          <div className="flex items-center justify-between mb-4">
            <Skeleton className="h-5 w-28" />
            <Skeleton className="w-8 h-8 rounded-full" />
          </div>
          <Skeleton className="h-10 w-full rounded-md" />
        </div>

        {/* Kapitel list skeleton */}
        <div className="flex-1 overflow-y-auto py-2 px-2">
          <div className="space-y-1">
            {[...Array(8)].map((_, i) => (
              <div
                key={i}
                className="flex items-center gap-2 py-2.5 px-3 rounded-md"
                style={{ paddingLeft: i === 1 || i === 2 ? "1.75rem" : i === 3 ? "2.75rem" : "0.75rem" }}
              >
                <Skeleton className="h-4 w-4 rounded-full shrink-0" />
                <Skeleton className="h-4 flex-1" style={{ maxWidth: i % 3 === 0 ? "120px" : "150px" }} />
              </div>
            ))}
          </div>
        </div>

        {/* Add button skeleton */}
        <div className="p-3 border-t border-sidebar-border">
          <Skeleton className="h-9 w-full rounded-md" />
        </div>
      </div>

      {/* Main Workspace Skeleton */}
      <div className="flex-1 overflow-hidden">
        <div className="h-full overflow-y-auto">
          <div className="max-w-4xl mx-auto py-12 px-8">
            {/* Kapitel header skeleton */}
            <div className="mb-8">
              <Skeleton className="h-9 w-80 mb-3" />
              <div className="flex items-center gap-4">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-4 w-24" />
              </div>
            </div>

            {/* Action bar skeleton */}
            <div className="flex items-center gap-3 mb-6">
              <Skeleton className="h-10 w-44 rounded-md" />
              <Skeleton className="h-10 w-40 rounded-md" />
              <div className="ml-auto flex items-center gap-3">
                <Skeleton className="h-8 w-20 rounded-md" />
                <Skeleton className="h-10 w-48 rounded-md" />
              </div>
            </div>

            {/* Combined text card skeleton */}
            <Card className="mb-8 p-8">
              <div className="flex items-center justify-between mb-6">
                <Skeleton className="h-6 w-40" />
                <div className="flex items-center gap-2">
                  <Skeleton className="h-8 w-8 rounded-md" />
                  <Skeleton className="h-8 w-8 rounded-md" />
                </div>
              </div>
              <div className="space-y-3">
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-5/6" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-2/3" />
              </div>
            </Card>

            {/* Run info skeleton */}
            <div className="mb-6 p-4 bg-muted/30 rounded-lg">
              <div className="flex items-start gap-6">
                <Skeleton className="h-4 w-28" />
                <Skeleton className="h-4 w-32" />
              </div>
              <div className="mt-3">
                <Skeleton className="h-4 w-full max-w-lg" />
              </div>
            </div>

            {/* Per-Quelle section skeleton */}
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <Skeleton className="h-5 w-40" />
                <Skeleton className="h-4 w-16" />
              </div>
              <div className="space-y-3">
                {[...Array(3)].map((_, i) => (
                  <Card key={i} className="p-5">
                    <div className="flex items-start justify-between mb-3">
                      <Skeleton className="h-5 w-56" />
                      <div className="flex items-center gap-1">
                        <Skeleton className="h-7 w-7 rounded-md" />
                        <Skeleton className="h-7 w-7 rounded-md" />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Skeleton className="h-4 w-full" />
                      <Skeleton className="h-4 w-full" />
                      <Skeleton className="h-4 w-2/3" />
                    </div>
                  </Card>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Right Quellen Panel Skeleton */}
      {showQuellenPanel && <QuellenPanelSkeleton />}
    </div>
  )
}
