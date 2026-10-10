import { AnimatePresence, motion } from "framer-motion";
import { Clock, LogOut, Menu, Monitor, Moon, Search, Sun, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { fmtRelative } from "@/lib/format";
import { useMotion } from "@/lib/motion";
import { useTheme, type ThemePref } from "@/lib/theme";
import { CommandPalette } from "./CommandPalette";
import { Logo } from "./Logo";
import { NAV } from "./nav";
import { NotificationsButton } from "./Notifications";

function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Main" className="flex flex-col gap-5 px-3 py-4">
      {NAV.map((g) => (
        <div key={g.group}>
          <div className="label mb-1.5 px-2.5">{g.group}</div>
          <ul className="space-y-0.5">
            {g.items.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    cn(
                      "group relative flex h-8 items-center gap-2.5 rounded px-2.5 text-base transition-colors",
                      isActive ? "bg-overlay text-fg" : "text-muted hover:bg-overlay/60 hover:text-fg",
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      {isActive && <span className="absolute -left-3 top-1.5 h-5 w-0.5 rounded-r bg-accent" aria-hidden />}
                      <item.icon className={cn("h-4 w-4", isActive ? "text-accent" : "text-faint group-hover:text-muted")} aria-hidden />
                      {item.label}
                    </>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}

function ThemeSwitcher() {
  const { pref, setPref } = useTheme();
  const opts: { v: ThemePref; icon: typeof Sun; label: string }[] = [
    { v: "dark", icon: Moon, label: "Dark" },
    { v: "light", icon: Sun, label: "Light" },
    { v: "system", icon: Monitor, label: "System" },
  ];
  return (
    <div role="radiogroup" aria-label="Theme" className="flex rounded border border-line bg-bg p-0.5">
      {opts.map((o) => (
        <button key={o.v} role="radio" aria-checked={pref === o.v} aria-label={`${o.label} theme`} title={`${o.label} theme`} onClick={() => setPref(o.v)} className={cn("flex h-6 flex-1 items-center justify-center rounded-sm text-faint", pref === o.v ? "bg-overlay text-fg" : "hover:text-muted")}>
          <o.icon className="h-3.5 w-3.5" />
        </button>
      ))}
    </div>
  );
}

function UserBlock() {
  const { user, workspace, logout } = useAuth();
  const navigate = useNavigate();
  return (
    <div className="space-y-3 border-t border-line p-3">
      <ThemeSwitcher />
      <div className="flex items-center gap-2.5">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-line bg-raised font-mono text-sm uppercase text-muted" aria-hidden>
          {(user?.display_name ?? "?").slice(0, 2)}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-base text-fg">{user?.display_name}</div>
          <div className="truncate text-xs text-faint">
            {workspace?.name} · {user?.role}
          </div>
        </div>
        <button
          aria-label="Sign out"
          title="Sign out"
          onClick={() => {
            logout();
            navigate("/");
          }}
          className="rounded p-1.5 text-faint hover:bg-overlay hover:text-fg"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

function DemoBanner() {
  const { workspace } = useAuth();
  if (!workspace?.is_demo) return null;
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-2 gap-y-0.5 border-b border-accent/25 bg-accent/[0.07] px-4 py-1.5 text-center text-sm text-muted">
      <span className="font-medium text-fg">Demo workspace</span>
      <span>Synthetic, labelled data only. Isolated to you and deleted</span>
      <span className="inline-flex items-center gap-1 text-fg">
        <Clock className="h-3 w-3" aria-hidden /> {fmtRelative(workspace.expires_at)}
      </span>
    </div>
  );
}

export function AppShell() {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { reduced } = useMotion();
  const mainRef = useRef<HTMLElement>(null);

  useEffect(() => setDrawer(false), [location.pathname]);
  useEffect(() => {
    mainRef.current?.focus({ preventScroll: true });
    window.scrollTo({ top: 0 });
  }, [location.pathname]);

  useEffect(() => {
    let pendingG = 0;
    const keymap = Object.fromEntries(NAV.flatMap((g) => g.items).map((i) => [i.key.split(" ")[1], i.to]));
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      const typing = t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName);
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
        return;
      }
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "/") {
        e.preventDefault();
        setPaletteOpen(true);
        return;
      }
      if (e.key === "g") {
        pendingG = Date.now();
        return;
      }
      if (pendingG && Date.now() - pendingG < 900 && keymap[e.key]) {
        navigate(keymap[e.key]);
      }
      pendingG = 0;
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [navigate]);

  return (
    <div className="min-h-screen bg-bg">
      <a href="#main" className="sr-only z-50 rounded bg-accent px-3 py-2 text-accent-fg focus:not-sr-only focus:fixed focus:left-3 focus:top-3">
        Skip to content
      </a>
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[232px] flex-col border-r border-line bg-surface lg:flex">
        <div className="flex h-14 items-center border-b border-line px-5">
          <NavLink to="/overview" aria-label="DataSentry overview">
            <Logo />
          </NavLink>
        </div>
        <div className="flex-1 overflow-y-auto">
          <SidebarNav />
        </div>
        <UserBlock />
      </aside>

      {/* Mobile drawer */}
      <AnimatePresence>
        {drawer && (
          <div className="fixed inset-0 z-40 lg:hidden">
            <motion.div className="absolute inset-0 bg-black/60" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reduced ? 0 : 0.15 }} onClick={() => setDrawer(false)} />
            <motion.aside
              role="dialog"
              aria-modal="true"
              aria-label="Navigation"
              initial={reduced ? false : { x: -280 }}
              animate={{ x: 0 }}
              exit={reduced ? { opacity: 0 } : { x: -280 }}
              transition={reduced ? { duration: 0 } : { type: "spring", stiffness: 420, damping: 40 }}
              className="absolute inset-y-0 left-0 flex w-[min(280px,86vw)] flex-col border-r border-line bg-surface"
            >
              <div className="flex h-14 items-center justify-between border-b border-line px-4">
                <Logo />
                <button aria-label="Close navigation" onClick={() => setDrawer(false)} className="rounded p-1.5 text-muted hover:bg-overlay">
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="flex-1 overflow-y-auto">
                <SidebarNav onNavigate={() => setDrawer(false)} />
              </div>
              <UserBlock />
            </motion.aside>
          </div>
        )}
      </AnimatePresence>

      <div className="lg:pl-[232px]">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-2 border-b border-line bg-bg/85 px-3 backdrop-blur-md sm:px-5">
          <button aria-label="Open navigation" onClick={() => setDrawer(true)} className="rounded p-1.5 text-muted hover:bg-overlay lg:hidden">
            <Menu className="h-5 w-5" />
          </button>
          <NavLink to="/overview" className="lg:hidden" aria-label="DataSentry overview">
            <Logo compact />
          </NavLink>
          <button onClick={() => setPaletteOpen(true)} className="ml-1 flex h-8 min-w-0 flex-1 items-center gap-2 rounded border border-line bg-surface px-2.5 text-left text-base text-faint transition-colors hover:border-line-strong sm:max-w-sm" aria-label="Search and commands">
            <Search className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">Search or jump to…</span>
            <span className="ml-auto hidden gap-0.5 sm:flex">
              <span className="kbd">⌘</span>
              <span className="kbd">K</span>
            </span>
          </button>
          <div className="ml-auto flex items-center gap-1">
            <NotificationsButton />
          </div>
        </header>
        <DemoBanner />
        <main id="main" ref={mainRef} tabIndex={-1} className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-5 focus:outline-none sm:px-6 sm:pt-7 lg:px-8">
          <Outlet />
        </main>
      </div>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  );
}
