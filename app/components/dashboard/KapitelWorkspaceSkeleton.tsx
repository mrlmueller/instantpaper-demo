import { Skeleton } from "@/components/ui/skeleton";

export function KapitelWorkspaceSkeleton() {
  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-4xl mx-auto py-12 px-8 space-y-8">
        {/* Header */}
        <div className="space-y-3">
          <Skeleton className="h-8 w-72" />
          <div className="flex flex-wrap gap-4">
            <Skeleton className="h-4 w-36" />
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-4 w-28" />
          </div>
        </div>

        {/* Action bar */}
        <div className="flex flex-wrap items-center gap-3">
          <Skeleton className="h-10 w-44 rounded-md" />
          <Skeleton className="h-10 w-44 rounded-md" />
          <Skeleton className="h-10 w-36 rounded-md" />
          <div className="flex items-center gap-2 ml-auto">
            <Skeleton className="h-8 w-24 rounded-md" />
            <Skeleton className="h-10 w-48 rounded-md" />
          </div>
        </div>

        {/* Combined card */}
        <div className="rounded-lg border border-border bg-card shadow-sm p-8 space-y-6">
          <div className="flex items-center justify-between">
            <Skeleton className="h-6 w-40" />
            <div className="flex items-center gap-2">
              <Skeleton className="h-9 w-24 rounded-md" />
              <Skeleton className="h-9 w-24 rounded-md" />
            </div>
          </div>
          <div className="space-y-3">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-11/12" />
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        </div>

        {/* Quellen list */}
        <div className="space-y-4">
          <Skeleton className="h-6 w-48" />
          <div className="space-y-3">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="rounded-lg border border-border bg-card px-5 py-4 flex items-start gap-3"
              >
                <Skeleton className="h-5 w-5 rounded-md mt-1" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-4 w-56" />
                  <Skeleton className="h-3 w-32" />
                  <Skeleton className="h-3 w-44" />
                </div>
                <div className="flex gap-2">
                  <Skeleton className="h-8 w-8 rounded-md" />
                  <Skeleton className="h-8 w-8 rounded-md" />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
