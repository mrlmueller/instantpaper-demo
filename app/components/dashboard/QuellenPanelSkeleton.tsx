import { Skeleton } from "@/components/ui/skeleton"
import { Card } from "@/components/ui/card"

export function QuellenPanelSkeleton() {
  return (
    <div className="w-[420px] border-l border-border bg-background flex flex-col">
      {/* Header skeleton */}
      <div className="p-4 border-b border-border">
        <div className="flex items-center justify-between mb-3">
          <div>
            <Skeleton className="h-5 w-24 mb-1" />
            <Skeleton className="h-3 w-16" />
          </div>
          <div className="flex items-center gap-1">
            <Skeleton className="h-8 w-8 rounded-md" />
            <Skeleton className="h-8 w-8 rounded-md" />
          </div>
        </div>
        <Skeleton className="h-10 w-full rounded-md" />
      </div>

      {/* Quellen list skeleton */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Section header */}
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Skeleton className="h-2 w-2 rounded-full" />
            <Skeleton className="h-3 w-32" />
          </div>
          {[...Array(3)].map((_, i) => (
            <Card key={i} className="p-3 relative overflow-hidden">
              {/* Color bar */}
              <div className="absolute top-0 left-0 right-0 h-1.5 bg-muted" />
              <div className="flex items-start gap-3" style={{ marginTop: "6px" }}>
                <div className="flex-1 min-w-0">
                  <Skeleton className="h-4 w-40 mb-1" />
                  <Skeleton className="h-3 w-24" />
                </div>
                <Skeleton className="h-5 w-5 rounded-full shrink-0" />
              </div>
            </Card>
          ))}
        </div>

        {/* Second section */}
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Skeleton className="h-2 w-2 rounded-full" />
            <Skeleton className="h-3 w-24" />
          </div>
          {[...Array(2)].map((_, i) => (
            <Card key={i} className="p-3">
              <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <Skeleton className="h-4 w-36 mb-1" />
                  <Skeleton className="h-3 w-20" />
                </div>
                <Skeleton className="h-5 w-5 rounded-full shrink-0" />
              </div>
            </Card>
          ))}
        </div>
      </div>

      {/* Add button skeleton */}
      <div className="p-4 border-t border-border">
        <Skeleton className="h-10 w-full rounded-md" />
      </div>
    </div>
  )
}
