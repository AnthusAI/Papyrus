import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { normalizeSiteBrandId } from "./lib/site-brand";

const BRAND_OVERRIDE_COOKIE = "papyrus-site-brand-override";

export function middleware(request: NextRequest) {
  const brandParam = request.nextUrl.searchParams.get("brand");
  const brandId = normalizeSiteBrandId(brandParam);
  if (!brandId) return NextResponse.next();

  const response = NextResponse.next();
  response.cookies.set(BRAND_OVERRIDE_COOKIE, brandId, {
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
    sameSite: "lax",
  });
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|icon).*)"],
};
