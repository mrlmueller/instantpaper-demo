import { NextRequest, NextResponse } from "next/server";

const PUBLIC_ROUTES = ["/login"];

// Lightweight JWT payload decode to check token expiry without verifying signature.
function isTokenValid(token?: string) {
  if (!token) return false;

  try {
    const parts = token.split(".");
    if (parts.length < 2) return false;

    const base64Url = parts[1];
    const normalized = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
    const payload = JSON.parse(atob(padded));

    if (typeof payload.exp !== "number") return false;
    return payload.exp * 1000 > Date.now();
  } catch (error) {
    console.warn("Failed to parse auth token", error);
    return false;
  }
}

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const token = request.cookies.get("__session")?.value;
  const hasValidToken = isTokenValid(token);
  const isPublicRoute = PUBLIC_ROUTES.some((route) =>
    pathname.startsWith(route)
  );
  const isLoginRoute = pathname.startsWith("/login");

  // Let users reach the login page if their cookie is invalid/expired.
  if (isLoginRoute) {
    if (hasValidToken) {
      return NextResponse.redirect(new URL("/dashboard", request.url));
    }

    const response = NextResponse.next();
    if (token && !hasValidToken) {
      response.cookies.delete("__session");
    }
    return response;
  }

  if (isPublicRoute) {
    return NextResponse.next();
  }

  if (!hasValidToken) {
    // If there's a token (even if expired), let the client handle refresh
    // Firebase Auth will automatically refresh using the refresh token
    if (token) {
      // Let the request through - client-side auth will handle it
      return NextResponse.next();
    }

    // No token at all - redirect to login
    const loginUrl = new URL("/login", request.url);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
