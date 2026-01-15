import { redirect } from "next/navigation";
import { getAuthSession } from "@/app/lib/auth/server-auth";
import { cookies } from "next/headers";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const { user, access } = await getAuthSession();
  const cookieStore = await cookies();
  const token = cookieStore.get("__session")?.value;

  // Redirect based on auth state
  if (user) {
    const hasAccess = Boolean((access?.fullAccess || access?.legacyApproved) && !access?.blocked);
    redirect(hasAccess ? "/dashboard" : "/activate");
  }

  // If there's a cookie (even if the token is stale/expired), let the app refresh it client-side.
  if (token) {
    redirect("/dashboard");
  }

  redirect("/login");
}
