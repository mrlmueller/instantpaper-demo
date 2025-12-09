import { Skeleton } from "@/components/ui/skeleton"
import { Card } from "@/components/ui/card"

export function QuellenPanelSkeleton() {
  return (
    <div className="w-96 border-l border-border bg-card flex flex-col">
      {/* Header skeleton */}
      <div className="p-4 border-b border-border">
        <div className="flex items-center justify-between">
          <Skeleton className="h-6 w-32" />
          <Skeleton className="h-8 w-8 rounded-md" />
        </div>
      </div>

      {/* Search skeleton */}
      <div className="px-4 pt-4">
        <Skeleton className="h-10 w-full rounded-md" />
      </div>

      {/* Tabs skeleton */}
      <div className="px-4 pt-4">
        <div className="flex gap-2">
          <Skeleton className="h-9 w-24 rounded-md" />
          <Skeleton className="h-9 w-16 rounded-md" />
        </div>
      </div>

      {/* Quellen list skeleton */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {[...Array(5)].map((_, i) => (
          <Card key={i} className="p-4">
            <div className="flex items-start gap-3">
              <Skeleton className="h-5 w-5 rounded shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <Skeleton className="h-4 w-48 mb-2" />
                <Skeleton className="h-3 w-20" />
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <Skeleton className="h-7 w-7 rounded-md" />
                <Skeleton className="h-7 w-7 rounded-md" />
              </div>
            </div>
          </Card>
        ))}
      </div>

      {/* Add button skeleton */}
      <div className="p-4 border-t border-border">
        <Skeleton className="h-10 w-full rounded-md" />
      </div>
    </div>
  )
}
