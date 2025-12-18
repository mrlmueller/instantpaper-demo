import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export default function QuellenManagerLoading() {
  return (
    <div className="min-h-screen bg-background">
      <div className="border-b border-border px-6 py-4 flex items-center gap-4">
        <Skeleton className="h-9 w-9" />
        <div>
          <Skeleton className="h-6 w-40 mb-1" />
          <Skeleton className="h-4 w-24" />
        </div>
      </div>
      <div className="border-b border-border px-6 py-3 flex items-center gap-4 flex-wrap">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-9 w-32" />
        <Skeleton className="h-9 w-32" />
        <div className="flex-1" />
        <Skeleton className="h-9 w-40" />
      </div>
      <div className="px-6 py-4">
        <Card className="p-4">
          <div className="space-y-3">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

