import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

export default function QuellenFinderLoading() {
  return (
    <div className="min-h-screen bg-background">
      <div className="border-b border-border px-6 py-4 flex items-center gap-4">
        <Skeleton className="h-9 w-9" />
        <div>
          <Skeleton className="h-6 w-40 mb-1" />
          <Skeleton className="h-4 w-32" />
        </div>
      </div>
      <div className="px-6 py-4">
        <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-4">
          <Card className="p-4 space-y-3">
            <Skeleton className="h-9 w-full" />
            {Array.from({ length: 10 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </Card>
          <Card className="p-4 space-y-4">
            <Skeleton className="h-10 w-56" />
            <Skeleton className="h-28 w-full" />
            <Skeleton className="h-10 w-48" />
            <Skeleton className="h-64 w-full" />
          </Card>
        </div>
      </div>
    </div>
  );
}

