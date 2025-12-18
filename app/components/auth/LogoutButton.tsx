"use client";

import { signOut } from "@/app/lib/firebase/auth";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";

export function LogoutButton() {
  const router = useRouter();

  const handleLogout = async () => {
    try {
      await signOut();
      // Reload to sync server and client after auth state change
      window.location.href = "/login";
    } catch (error) {
      console.error("Logout failed:", error);
    }
  };

  return (
    <Button onClick={handleLogout} variant="outline">
      Sign out
    </Button>
  );
}
