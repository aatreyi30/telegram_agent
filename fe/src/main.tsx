import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./styles/index.css";
import { AuthProvider, ProtectedRoute } from "./providers/auth";
import { AppLayout } from "./components/AppLayout";
import { Landing } from "./routes/Landing";
import { Login } from "./routes/Login";
import { Overview } from "./routes/Overview";
import { Insights } from "./routes/Insights";
import { Analytics } from "./routes/Analytics";
import { DayView } from "./routes/DayView";
import { Competitors } from "./routes/Competitors";
import { Plan } from "./routes/Plan";
import { Drafts } from "./routes/Drafts";
import { Queue } from "./routes/Queue";
import { Settings } from "./routes/Settings";

const qc = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false, staleTime: 30_000 } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/login" element={<Login />} />
            <Route
              path="/app"
              element={
                <ProtectedRoute>
                  <AppLayout />
                </ProtectedRoute>
              }
            >
              <Route index element={<Overview />} />
              <Route path="insights" element={<Insights />} />
              <Route path="analytics" element={<Analytics />} />
              <Route path="weekly" element={<Navigate to="/app/plan" replace />} />
              <Route path="day" element={<DayView />} />
              <Route path="competitors" element={<Competitors />} />
              <Route path="plan" element={<Plan />} />
              <Route path="drafts" element={<Drafts />} />
              <Route path="queue" element={<Queue />} />
              <Route path="settings" element={<Settings />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>
);
