import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { getSiteBrand } from "./lib/site-brand";
import { getSiteEnv, isIndexable } from "./lib/site-env";
import { getStagingAccess } from "./lib/staging-gate";
import {
  isPreviewGatedPath,
  isStaticPreviewEnabled,
  previewRewritePathname,
  shouldRewriteToPreview,
} from "./lib/staging-preview-object";

function usesNewsroomRootPaths(): boolean {
  const brand = getSiteBrand();
  return brand.rootRoute?.kind === "newsroom" && brand.newsroomBasePath === "";
}

function isStaticOrApiPath(pathname: string): boolean {
  return (
    pathname.startsWith("/_next")
    || pathname.startsWith("/api")
    || pathname === "/favicon.ico"
    || pathname.startsWith("/icon")
    || /\.[a-zA-Z0-9]+$/.test(pathname)
  );
}

function isStagingGatedPath(pathname: string): boolean {
  if (isStaticOrApiPath(pathname)) return false;
  if (pathname === "/robots.txt") return false;
  if (pathname === "/newsroom" || pathname.startsWith("/newsroom/")) return false;
  return true;
}

function routeRequest(request: NextRequest): NextResponse {
  if (isStaticPreviewEnabled() && shouldRewriteToPreview(request.nextUrl.pathname)) {
    const rewriteUrl = request.nextUrl.clone();
    rewriteUrl.pathname = previewRewritePathname(request.nextUrl.pathname);
    return NextResponse.rewrite(rewriteUrl);
  }
  if (!usesNewsroomRootPaths()) {
    return NextResponse.next();
  }

  const { pathname } = request.nextUrl;
  if (isStaticOrApiPath(pathname)) {
    return NextResponse.next();
  }

  if (pathname === "/newsroom" || pathname === "/newsroom/") {
    return NextResponse.redirect(new URL("/", request.url));
  }
  if (pathname.startsWith("/newsroom/")) {
    const target = pathname.slice("/newsroom".length) || "/";
    return NextResponse.redirect(new URL(`${target}${request.nextUrl.search}`, request.url));
  }

  if (pathname === "/" || pathname === "") {
    return NextResponse.next();
  }

  if (!pathname.startsWith("/newsroom")) {
    const rewriteUrl = request.nextUrl.clone();
    rewriteUrl.pathname = `/newsroom${pathname}`;
    return NextResponse.rewrite(rewriteUrl);
  }

  return NextResponse.next();
}

export async function middleware(request: NextRequest): Promise<NextResponse> {
  let sessionResponse: NextResponse | null = null;
  const { pathname } = request.nextUrl;
  const gated = isStaticPreviewEnabled() ? isPreviewGatedPath(pathname) : isStagingGatedPath(pathname);
  if (getSiteEnv() === "staging" && gated) {
    sessionResponse = NextResponse.next();
    const access = await getStagingAccess(request, sessionResponse);
    if (access === "anonymous") {
      return withRobotsHeader(NextResponse.redirect(new URL("/newsroom", request.url)));
    }
    if (access === "forbidden") {
      return withRobotsHeader(new NextResponse("Staging is limited to editors and admins.", { status: 403 }));
    }
  }

  const response = routeRequest(request);
  if (sessionResponse) {
    for (const cookie of sessionResponse.headers.getSetCookie()) {
      response.headers.append("set-cookie", cookie);
    }
  }
  return withRobotsHeader(response);
}

function withRobotsHeader(response: NextResponse): NextResponse {
  if (!isIndexable()) response.headers.set("X-Robots-Tag", "noindex, nofollow");
  return response;
}

export const config = {
  runtime: "nodejs",
  matcher: ["/((?!_next/static|_next/image|favicon.ico|icon).*)"],
};
