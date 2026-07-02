import type { Metadata } from "next";
import { SettingsPage } from "../../components/settings-page";
import { SITE_BRAND } from "../../lib/site-brand";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: `Settings | ${SITE_BRAND.articleTitleSuffix}`,
  description: `Reader presentation and theme settings for ${SITE_BRAND.articleTitleSuffix}.`,
};

export default function Settings() {
  return <SettingsPage />;
}
