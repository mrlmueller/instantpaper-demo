import { NextRequest, NextResponse } from "next/server";

const PUBLIC_ROUTES = ["/login"];
const ACCESS_WHITELIST_PREFIXES = ["/login", "/activate", "/admin"];

// Lightweight JWT payload decode to check token expiry without verifying signature.
function isTokenValid(token?: string) {
  if (!token) return false;

  try {
    const payload = readJwtPayload(token);
    if (!payload || typeof payload.exp !== "number") return false;
    return payload.exp * 1000 > Date.now();
  } catch (error) {
    console.warn("Failed to parse auth token", error);
    return false;
  }
}

function readJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split(".");
    if (parts.length < 2) return null;

    const base64Url = parts[1];
    const normalized = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
    return JSON.parse(atob(padded)) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function hasAccessFromJwt(token: string): { hasAccess: boolean; blocked: boolean } {
  const payload = readJwtPayload(token) || {};
  const fullAccess = payload["fullAccess"] === true;
  const legacyApproved = payload["approved"] === true;
  const blocked = payload["blocked"] === true;
  return { hasAccess: (fullAccess || legacyApproved) && !blocked, blocked };
}

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const token = request.cookies.get("__session")?.value;
  const hasValidToken = isTokenValid(token);
  const isPublicRoute = PUBLIC_ROUTES.some((route) =>
    pathname.startsWith(route)
  );
  const isLoginRoute = pathname.startsWith("/login");
  const isApiRoute = pathname.startsWith("/api");

  // Never interfere with API routes (they return JSON/401 on their own).
  if (isApiRoute) {
    return NextResponse.next();
  }

  // Let users reach the login page if their cookie is invalid/expired.
  if (isLoginRoute) {
    if (hasValidToken) {
      const { hasAccess } = hasAccessFromJwt(token || "");
      return NextResponse.redirect(new URL(hasAccess ? "/dashboard" : "/activate", request.url));
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

  // Access gate: if logged in but missing `fullAccess` (or legacy `approved`), force /activate (except whitelist).
  const isWhitelisted = ACCESS_WHITELIST_PREFIXES.some((p) => pathname.startsWith(p));
  const access = hasAccessFromJwt(token || "");

  if (pathname.startsWith("/activate")) {
    if (access.hasAccess) {
      return NextResponse.redirect(new URL("/dashboard", request.url));
    }
    return NextResponse.next();
  }

  if (!isWhitelisted && !access.hasAccess) {
    return NextResponse.redirect(new URL("/activate", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
