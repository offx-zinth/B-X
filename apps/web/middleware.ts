import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Edge guard: protected workspaces require an auth signal before render.
// HttpOnly access_token cookie (browser sessions) or a stored bearer session
// (API clients) both satisfy it; the API remains the authority for validity.
const PROTECTED = ["/workspace", "/dashboard", "/simulations", "/reports", "/optimization", "/settings", "/data"];

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (!PROTECTED.some(p => pathname === p || pathname.startsWith(p + "/"))) {
    return NextResponse.next();
  }
  const cookie = req.cookies.get("access_token") || req.cookies.get("xray_session");
  const header = req.headers.get("authorization") || "";
  if (!cookie && !header.startsWith("Bearer ")) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/workspace/:path*", "/dashboard/:path*", "/simulations/:path*", "/reports/:path*",
            "/optimization/:path*", "/settings/:path*", "/data/:path*"],
};
