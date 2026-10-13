import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { signInAgainHref } from "@/lib/auth/session-end";
import { tokenExpiry } from "@/lib/auth/token-expiry";

const SESSION_COOKIE = "idp_access_token";

/**
 * Pages that need a session send someone without one to sign in, and back to
 * the same page (query included) afterwards. A session that has run out says
 * so on the sign-in page, rather than arriving there unexplained.
 */
export function proxy(request: NextRequest) {
  const here = `${request.nextUrl.pathname}${request.nextUrl.search}`;
  const token = request.cookies.get(SESSION_COOKIE)?.value ?? "";

  if (!token) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", here);
    return NextResponse.redirect(loginUrl);
  }

  const exp = tokenExpiry(token);
  if (exp !== null && exp * 1000 <= Date.now()) {
    const response = NextResponse.redirect(new URL(signInAgainHref(here), request.url));
    response.cookies.delete(SESSION_COOKIE);
    return response;
  }

  return NextResponse.next();
}

export const config = {
  // Every page that requires a session. Home, sign-in, shared dashboards and
  // the system status page work without one and are left alone.
  matcher: [
    "/projects/:path*",
    "/runs/:path*",
    "/datasets/:path*",
    "/notifications/:path*",
    "/people/:path*",
    "/organisations/:path*",
    "/audits/:path*",
    "/connectors/:path*",
    "/settings/:path*",
  ],
};
