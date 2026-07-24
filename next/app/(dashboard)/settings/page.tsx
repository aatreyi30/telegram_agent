import { redirect } from "next/navigation";

// /settings has no content of its own — it always redirects to the first (and only
// universally-visible) settings page. Owner-only pages guard themselves via <OwnerOnly>.
export default function SettingsIndexPage() {
  redirect("/settings/profile");
}
