import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { signInAgainHref } from "@/lib/auth/session-end";
import { tokenExpiry } from "@/lib/auth/token-expiry";
import { embedOrigins, frameAncestors } from "@/lib/embed-origins";

const SESSION_COOKIE = "idp_access_token";

/**
 * Pages that need a session send someone without one to sign in, and back to
 * the same page (query included) afterwards. A session that has run out says
 * so on the sign-in page, rather than arriving there unexplained.
 */
export function proxy(request: NextRequest) {
  if (request.nextUrl.pathname.startsWith("/embed/")) {
    // An embedded dashboard needs no session; it may be framed by the sites
    // an administrator lists, read now so a change needs only a restart.
    const response = NextResponse.next();
    response.headers.set("Content-Security-Policy", `frame-ancestors ${frameAncestors(embedOrigins())}`);
    return response;
  }

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
  // Every page that requires a session, and embedded dashboards for their
  // frame header. Home, sign-in, shared dashboards and the system status page
  // work without one and are left alone.
  matcher: [
    "/embed/:path*",
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
