import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { getSiteBrand } from "./lib/site-brand";
import { newsroomHref } from "./lib/newsroom-base-path";
import { getReaderBasePath } from "./lib/reader-base-path";
import { isStagingGatedPath, isStaticOrApiPath } from "./lib/staging-gated-path";
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

function isStagingGatedPathForBrand(pathname: string): boolean {
  return isStagingGatedPath(pathname, getReaderBasePath(), usesNewsroomRootPaths());
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
    return NextResponse.redirect(new URL(`/${request.nextUrl.search}`, request.url));
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
  const gated = isStaticPreviewEnabled() && !usesNewsroomRootPaths()
    ? isPreviewGatedPath(pathname)
    : isStagingGatedPathForBrand(pathname);
  if (getSiteEnv() === "staging" && gated) {
    sessionResponse = NextResponse.next();
    const access = await getStagingAccess(request, sessionResponse);
    if (access === "anonymous") {
      return withRobotsHeader(NextResponse.redirect(new URL(newsroomHref(), request.url)));
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
