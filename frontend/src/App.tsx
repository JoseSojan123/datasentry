import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Toaster } from "sonner";
import { AppShell } from "./components/layout/AppShell";
import { LogoMark } from "./components/layout/Logo";
import { useAuth } from "./lib/auth";
import { useTheme } from "./lib/theme";

const Landing = lazy(() => import("./pages/Landing"));
const Auth = lazy(() => import("./pages/Auth"));
const Overview = lazy(() => import("./pages/Overview"));
const Datasets = lazy(() => import("./pages/Datasets"));
const NewDataset = lazy(() => import("./pages/NewDataset"));
const DatasetDetail = lazy(() => import("./pages/DatasetDetail"));
const Compare = lazy(() => import("./pages/Compare"));
const DriftList = lazy(() => import("./pages/DriftList"));
const DriftDetail = lazy(() => import("./pages/DriftDetail"));
const Models = lazy(() => import("./pages/Models"));
const ModelDetail = lazy(() => import("./pages/ModelDetail"));
const Lineage = lazy(() => import("./pages/Lineage"));
const Incidents = lazy(() => import("./pages/Incidents"));
const IncidentDetail = lazy(() => import("./pages/IncidentDetail"));
const Remediation = lazy(() => import("./pages/Remediation"));
const Jobs = lazy(() => import("./pages/Jobs"));
const Activity = lazy(() => import("./pages/Activity"));
const Settings = lazy(() => import("./pages/Settings"));
const Docs = lazy(() => import("./pages/Docs"));
const NotFound = lazy(() => import("./pages/NotFound"));

function Splash() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center" role="status" aria-label="Loading">
      <LogoMark className="h-8 w-8 animate-pulse opacity-70" />
    </div>
  );
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const loc = useLocation();
  if (status === "loading") return <Splash />;
  if (status === "anonymous") return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
  return <>{children}</>;
}

function PublicOnly({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  if (status === "loading") return <Splash />;
  if (status === "authenticated") return <Navigate to="/overview" replace />;
  return <>{children}</>;
}

export function App() {
  const { resolved } = useTheme();
  return (
    <>
      <Suspense fallback={<Splash />}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<PublicOnly><Auth mode="login" /></PublicOnly>} />
          <Route path="/register" element={<PublicOnly><Auth mode="register" /></PublicOnly>} />
          <Route
            element={
              <RequireAuth>
                <AppShell />
              </RequireAuth>
            }
          >
            <Route path="/overview" element={<Suspense fallback={<Splash />}><Overview /></Suspense>} />
            <Route path="/datasets" element={<Suspense fallback={<Splash />}><Datasets /></Suspense>} />
            <Route path="/datasets/new" element={<Suspense fallback={<Splash />}><NewDataset /></Suspense>} />
            <Route path="/datasets/:id" element={<Suspense fallback={<Splash />}><DatasetDetail /></Suspense>} />
            <Route path="/datasets/:id/compare" element={<Suspense fallback={<Splash />}><Compare /></Suspense>} />
            <Route path="/drift" element={<Suspense fallback={<Splash />}><DriftList /></Suspense>} />
            <Route path="/drift/:id" element={<Suspense fallback={<Splash />}><DriftDetail /></Suspense>} />
            <Route path="/models" element={<Suspense fallback={<Splash />}><Models /></Suspense>} />
            <Route path="/models/:id" element={<Suspense fallback={<Splash />}><ModelDetail /></Suspense>} />
            <Route path="/lineage" element={<Suspense fallback={<Splash />}><Lineage /></Suspense>} />
            <Route path="/incidents" element={<Suspense fallback={<Splash />}><Incidents /></Suspense>} />
            <Route path="/incidents/:id" element={<Suspense fallback={<Splash />}><IncidentDetail /></Suspense>} />
            <Route path="/remediation" element={<Suspense fallback={<Splash />}><Remediation /></Suspense>} />
            <Route path="/jobs" element={<Suspense fallback={<Splash />}><Jobs /></Suspense>} />
            <Route path="/activity" element={<Suspense fallback={<Splash />}><Activity /></Suspense>} />
            <Route path="/settings" element={<Suspense fallback={<Splash />}><Settings /></Suspense>} />
            <Route path="/docs" element={<Suspense fallback={<Splash />}><Docs /></Suspense>} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
      <Toaster theme={resolved} position="bottom-right" toastOptions={{ className: "!bg-surface !border-line-strong !text-fg !font-sans" }} />
    </>
  );
}
