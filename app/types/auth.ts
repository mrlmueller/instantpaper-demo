import type { AccessState } from '@/app/lib/firebase/auth';

export interface User {
  uid: string;
  email: string | null;
  displayName: string | null;
  photoURL: string | null;
  emailVerified: boolean;
}

export interface AuthContextType {
  user: User | null;
  access: AccessState;
  effectiveBlocked: boolean;
  loading: boolean;
}
