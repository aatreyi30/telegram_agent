import { ClientLayout } from "@/providers/ClientLayout";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return <ClientLayout>{children}</ClientLayout>;
}
