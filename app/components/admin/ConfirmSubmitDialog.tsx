'use client';

import { useFormStatus } from 'react-dom';
import { Loader2 } from 'lucide-react';
import * as AlertDialogPrimitive from '@radix-ui/react-alert-dialog';

import { buttonVariants } from '@/components/ui/button';
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { cn } from '@/lib/utils';

type ButtonVariant = 'default' | 'destructive' | 'outline' | 'secondary' | 'ghost' | 'link';
type ButtonSize = 'default' | 'sm' | 'lg' | 'icon' | 'icon-sm' | 'icon-lg';

function PendingSpinner({ className }: { className?: string }) {
  return <Loader2 className={className ?? 'h-4 w-4 animate-spin'} />;
}

export function ConfirmSubmitDialog({
  triggerLabel,
  triggerVariant = 'default',
  triggerSize = 'sm',
  triggerClassName,
  title,
  description,
  confirmLabel,
  confirmVariant = 'destructive',
  confirmSize = 'sm',
  formId,
  confirmClassName,
  disabled,
}: {
  triggerLabel: string;
  triggerVariant?: ButtonVariant;
  triggerSize?: ButtonSize;
  title: string;
  description?: string;
  confirmLabel: string;
  confirmVariant?: ButtonVariant;
  confirmSize?: ButtonSize;
  formId?: string;
  confirmClassName?: string;
  triggerClassName?: string;
  disabled?: boolean;
}) {
  const { pending } = useFormStatus();

  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <button
          type="button"
          className={cn(buttonVariants({ variant: triggerVariant, size: triggerSize }), triggerClassName)}
          disabled={disabled || pending}
        >
          {triggerLabel}
        </button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          {description ? <AlertDialogDescription>{description}</AlertDialogDescription> : null}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel type="button" disabled={pending}>
            Abbrechen
          </AlertDialogCancel>
          <AlertDialogPrimitive.Action asChild>
            <button
              type="submit"
              form={formId}
              className={cn(
                buttonVariants({ variant: confirmVariant, size: confirmSize }),
                confirmClassName
              )}
              disabled={pending}
            >
              {pending ? <PendingSpinner className="h-4 w-4 animate-spin" /> : null}
              <span>{confirmLabel}</span>
            </button>
          </AlertDialogPrimitive.Action>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
