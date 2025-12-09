'use client';

import { useState } from 'react';
import { FileText } from 'lucide-react';
import { signInWithGoogle } from '@/app/lib/firebase/auth';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

function GoogleIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
        fill="#4285F4"
      />
      <path
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
        fill="#34A853"
      />
      <path
        d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
        fill="#FBBC05"
      />
      <path
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
        fill="#EA4335"
      />
    </svg>
  );
}

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleGoogleLogin = async () => {
    setLoading(true);
    setError(null);
    try {
      await signInWithGoogle();
      window.location.href = '/dashboard';
    } catch (err: any) {
      console.error('Login failed:', err);
      setError(err.message || 'Login fehlgeschlagen. Bitte erneut versuchen.');
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-primary/10 mb-6">
            <FileText className="h-8 w-8 text-primary" />
          </div>
          <h1 className="text-2xl font-semibold text-foreground mb-2">InstantPaper</h1>
          <p className="text-muted-foreground">Dein Schreibbegleiter für wissenschaftliche Arbeiten</p>
        </div>

        <Card className="border-border shadow-sm">
          <CardHeader className="text-center pb-4">
            <CardTitle className="text-xl">Willkommen zurück</CardTitle>
            <CardDescription>Melde dich an, um mit deiner Arbeit fortzufahren</CardDescription>
          </CardHeader>
          <CardContent className="pt-2">
            <Button
              onClick={handleGoogleLogin}
              variant="outline"
              className="w-full h-12 text-base font-medium bg-transparent"
              disabled={loading}
            >
              <GoogleIcon className="h-5 w-5 mr-3" />
              {loading ? 'Wird geladen...' : 'Mit Google anmelden'}
            </Button>

            {error && <p className="text-sm text-destructive text-center mt-3">{error}</p>}

            <p className="text-xs text-muted-foreground text-center mt-6">
              Mit der Anmeldung akzeptierst du unsere{' '}
              <a href="#" className="text-primary hover:underline">
                Nutzungsbedingungen
              </a>{' '}
              und{' '}
              <a href="#" className="text-primary hover:underline">
                Datenschutzrichtlinie
              </a>
              .
            </p>
          </CardContent>
        </Card>

        <p className="text-xs text-muted-foreground text-center mt-8">
          Verwandle deine Quellen in fertige Kapitel – strukturiert und wissenschaftlich.
        </p>
      </div>
    </div>
  );
}
