"use client";

import { cn } from "@/lib/utils";
import { Check, Trophy } from "lucide-react";

interface ProcessingStepperProps {
  hasQuellen: boolean;
  hasCombined: boolean;
  hasGekuerzt: boolean;
  hasVerbessert: boolean;
}

const stages = [
  { id: "quellen", label: "Quellen" },
  { id: "combined", label: "Kombiniert" },
  { id: "gekuerzt", label: "Gekürzt" },
  { id: "verbessert", label: "Verbessert" },
];

export function ProcessingStepper({
  hasQuellen,
  hasCombined,
  hasGekuerzt,
  hasVerbessert,
}: ProcessingStepperProps) {
  // Determine current stage based on what exists
  const getCurrentStageIndex = () => {
    if (hasVerbessert) return 3;
    if (hasGekuerzt) return 2;
    if (hasCombined) return 1;
    if (hasQuellen) return 0;
    return -1;
  };

  const currentStageIndex = getCurrentStageIndex();
  const isFullyComplete = hasVerbessert;

  return (
    <div className="flex items-center justify-center gap-1.5 mb-6">
      {stages.map((stage, index) => {
        const isComplete = index < currentStageIndex || isFullyComplete;
        const isCurrent = index === currentStageIndex && !isFullyComplete;

        return (
          <div
            key={stage.id}
            className={cn(
              "px-3 py-1.5 rounded-full text-xs font-medium transition-all flex items-center gap-1.5",
              isComplete && "bg-primary text-primary-foreground",
              isCurrent &&
                "bg-primary/15 text-primary ring-1 ring-primary/30",
              !isComplete && !isCurrent && "bg-muted/50 text-muted-foreground"
            )}
          >
            {isComplete && <Check className="h-3 w-3" />}
            {stage.label}
          </div>
        );
      })}
      {isFullyComplete && (
        <div className="ml-2 px-3 py-1.5 rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400 text-xs font-medium flex items-center gap-1.5">
          <Trophy className="h-3 w-3" />
          Fertig!
        </div>
      )}
    </div>
  );
}
