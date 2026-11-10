import { useQuery } from "@tanstack/react-query";
import { BarChart3, BookText, BrainCircuit, Database, FileText, GitPullRequest, LayoutDashboard, LogOut, Settings as SettingsIcon } from "lucide-react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Loading, cx } from "./components/ui";
import { get, getToken, signOut, type Health, type Overview as OverviewData } from "./lib/api";
import Audit from "./pages/Audit";
import Data from "./pages/Data";
import Insights from "./pages/Insights";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Memory from "./pages/Memory";
import Overview from "./pages/Overview";
import ProposalDetail from "./pages/ProposalDetail";
import RequirementDetail from "./pages/RequirementDetail";
import Requirements from "./pages/Requirements";
import Reviews from "./pages/Reviews";
import Settings from "./pages/Settings";
import Setup from "./pages/Setup";

function Shell() {
  const location = useLocation();
  const me = useQuery({ queryKey: ["me"], queryFn: () => get<{ name: string }>("/me") });
  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: () => get<OverviewData>("/overview"),
    refetchInterval: 2000,
  });
  const awaiting = overview.data?.stats.awaiting ?? 0;
  const initial = me.data?.name?.[0]?.toUpperCase() ?? "";

  const nav = [
    { to: "/", label: "Overview", icon: LayoutDashboard, badge: awaiting },
    { to: "/requirements", label: "Requirements", icon: FileText },
    { to: "/reviews", label: "PR reviews", icon: GitPullRequest },
    { to: "/insights", label: "Insights", icon: BarChart3 },
    { to: "/memory", label: "Memory", icon: BrainCircuit },
    { to: "/audit", label: "Audit trail", icon: BookText },
    { to: "/data", label: "Data", icon: Database },
    { to: "/settings", label: "Settings", icon: SettingsIcon },
  ];

  return (
    <div className="min-h-dvh lg:pl-64">
      <aside className="z-20 flex items-center gap-2 bg-ink px-3 py-2.5 text-paper lg:fixed lg:inset-y-0 lg:left-0 lg:w-64 lg:flex-col lg:items-stretch lg:gap-0 lg:overflow-hidden lg:px-3.5 lg:py-6">
        <div className="pointer-events-none absolute -top-24 -left-24 size-72 rounded-full bg-gold-bright/12 blur-3xl max-lg:hidden" />
        <span className="relative flex shrink-0 items-center gap-2.5 lg:mb-8 lg:px-2.5">
          <img src="/favicon.svg" alt="" className="size-7 rounded-md ring-1 ring-white/15" />
          <span className="font-serif text-[1.4rem] font-medium tracking-tight max-sm:hidden">Countersign</span>
        </span>
        <nav className="relative flex min-w-0 flex-1 gap-0.5 overflow-x-auto [scrollbar-width:none] lg:flex-none lg:flex-col lg:gap-1 lg:overflow-visible">
          {nav.map(({ to, label, icon: Icon, badge }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              aria-label={label}
              className={({ isActive }) =>
                cx("relative flex shrink-0 items-center gap-2.5 rounded-xl px-2.5 py-2.5 text-sm font-medium whitespace-nowrap transition-colors",
                  isActive ? "text-white" : "text-paper/60 hover:text-white")
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <motion.span layoutId="nav-pill" className="absolute inset-0 rounded-xl bg-white/12 ring-1 ring-white/10" transition={{ type: "spring", stiffness: 420, damping: 34 }} />
                  )}
                  <Icon className="relative size-[18px]" />
                  <span className="relative max-lg:hidden">{label}</span>
                  {!!badge && (
                    <span className="relative ml-auto rounded-full bg-gold-bright px-1.5 text-xs font-bold text-ink tabular-nums">{badge}</span>
                  )}
                </>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="relative flex shrink-0 items-center gap-2.5 lg:mt-auto lg:rounded-xl lg:bg-white/6 lg:p-2.5">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-gold-bright text-sm font-bold text-ink max-lg:hidden">{initial}</span>
          <div className="min-w-0 flex-1 max-lg:hidden">
            <div className="truncate text-sm font-semibold">{me.data?.name ?? " "}</div>
            <div className="text-xs text-paper/50">Approver</div>
          </div>
          <button aria-label="Sign out" title="Sign out" onClick={signOut} className="rounded-md p-1.5 text-paper/60 transition-colors hover:bg-white/10 hover:text-white">
            <LogOut className="size-4" />
          </button>
        </div>
      </aside>

      <main className="mx-auto max-w-6xl px-5 py-8 lg:px-10 lg:py-10">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
          >
            <ErrorBoundary key={location.pathname}>
            <Routes location={location}>
              <Route path="/" element={<Overview />} />
              <Route path="/requirements" element={<Requirements />} />
              <Route path="/requirements/:id" element={<RequirementDetail />} />
              <Route path="/proposals/:id" element={<ProposalDetail />} />
              <Route path="/reviews" element={<Reviews />} />
              <Route path="/insights" element={<Insights />} />
              <Route path="/memory" element={<Memory />} />
              <Route path="/audit" element={<Audit />} />
              <Route path="/data" element={<Data />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
            </ErrorBoundary>
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}

function Screen() {
  const { pathname } = useLocation();
  const health = useQuery({ queryKey: ["health"], queryFn: () => get<Health>("/health") });
  if (!health.data) {
    return (
      <div className="flex min-h-dvh items-center justify-center px-6 text-center">
        {health.isError
          ? <p className="max-w-sm text-sm text-ink-2">Countersign's server is not responding. Check that the backend is running, then reload this page.</p>
          : <Loading />}
      </div>
    );
  }
  const { configured } = health.data;
  if (pathname === "/welcome") return <Landing configured={configured} />;
  if (!configured) return pathname === "/setup" ? <Setup needs={health.data.needs} /> : <Landing configured={false} />;
  if (!getToken()) return pathname === "/login" ? <Login /> : <Landing configured />;
  return <Shell />;
}

export default function App() {
  return (
    <MotionConfig reducedMotion="user">
      <Screen />
    </MotionConfig>
  );
}
