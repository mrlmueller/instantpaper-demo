"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="dashboard-page">
      <div className="dashboard-main">
        <Card className="hero-panel hero-panel-flat rounded-[28px] border-border/70 bg-card/95 shadow-sm">
          <CardHeader>
            <div className="section-eyebrow">Loading run</div>
            <CardTitle className="hero-title">Preparing notebook artifacts…</CardTitle>
            <p className="hero-copy">Reading cached run files, building the lightweight review view, and preparing the active tab.</p>
          </CardHeader>
          <CardContent>
            <div className="hero-actions hero-actions-grid">
              {Array.from({ length: 4 }, (_, index) => (
                <Skeleton className="h-28 rounded-xl" key={index} />
              ))}
            </div>
          </CardContent>
        </Card>
        <Card className="content-panel content-panel-wide rounded-[24px] border-border/70 bg-card/95 shadow-sm">
          <CardContent className="pt-6">
            <div className="stack gap-4">
              {Array.from({ length: 6 }, (_, index) => (
                <Skeleton className="h-[72px] rounded-xl" key={index} />
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
