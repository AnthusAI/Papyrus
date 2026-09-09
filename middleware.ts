import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { normalizeSiteBrandId } from "./lib/site-brand";

const BRAND_OVERRIDE_COOKIE = "papyrus-site-brand-override";

function usesNewsroomRootPaths(request: NextRequest): boolean {
  const cookieBrand = request.cookies.get(BRAND_OVERRIDE_COOKIE)?.value;
  const brandId = normalizeSiteBrandId(cookieBrand)
    ?? normalizeSiteBrandId(request.nextUrl.searchParams.get("brand"))
    ?? normalizeSiteBrandId(process.env.NEXT_PUBLIC_PAPYRUS_SITE_BRAND ?? process.env.PAPYRUS_SITE_BRAND);
  return brandId === "pilobol-us";
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
  const brandParam = request.nextUrl.searchParams.get("brand");
  const brandId = normalizeSiteBrandId(brandParam);
  let response: NextResponse | null = null;

  if (brandId) {
    response = NextResponse.next();
    response.cookies.set(BRAND_OVERRIDE_COOKIE, brandId, {
      path: "/",
      maxAge: 60 * 60 * 24 * 30,
      sameSite: "lax",
    });
  }

  if (!usesNewsroomRootPaths(request)) {
    return response ?? NextResponse.next();
  }

  const { pathname } = request.nextUrl;
  if (isStaticOrApiPath(pathname)) {
    return response ?? NextResponse.next();
  }

  if (pathname === "/newsroom" || pathname === "/newsroom/") {
    return NextResponse.redirect(new URL("/", request.url));
  }
  if (pathname.startsWith("/newsroom/")) {
    const target = pathname.slice("/newsroom".length) || "/";
    return NextResponse.redirect(new URL(`${target}${request.nextUrl.search}`, request.url));
  }

  if (pathname === "/" || pathname === "") {
    return response ?? NextResponse.next();
  }

  if (!pathname.startsWith("/newsroom")) {
    const rewriteUrl = request.nextUrl.clone();
    rewriteUrl.pathname = `/newsroom${pathname}`;
    const rewrite = NextResponse.rewrite(rewriteUrl);
    if (response) {
      for (const cookie of response.cookies.getAll()) {
        rewrite.cookies.set(cookie);
      }
    }
    return rewrite;
  }

  return response ?? NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|icon).*)"],
};
