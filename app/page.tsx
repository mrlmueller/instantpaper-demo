import { redirect } from "next/navigation";
import { getAuthUser } from "@/app/lib/auth/server-auth";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const user = await getAuthUser();

  // Redirect based on auth state
  if (user) {
    redirect("/dashboard");
  } else {
    redirect("/login");
  }
}
