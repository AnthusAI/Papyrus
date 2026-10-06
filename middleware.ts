import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { getSiteBrand } from "./lib/site-brand";

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

export function middleware(request: NextRequest) {
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

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|icon).*)"],
};
