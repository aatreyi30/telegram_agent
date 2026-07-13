// Shared by the profile and channels settings pages for inline save-result feedback.
export function Note({ ok, msg }: { ok: boolean; msg: string }) {
  return <p className={ok ? "text-sm text-success" : "text-sm text-destructive"}>{msg}</p>;
}
