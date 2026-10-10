import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type ThemePref = "dark" | "light" | "system";

interface ThemeCtx {
  pref: ThemePref;
  resolved: "dark" | "light";
  setPref: (p: ThemePref) => void;
  reducedMotion: boolean;
  setReducedMotion: (v: boolean | null) => void;
}

const Ctx = createContext<ThemeCtx | null>(null);

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function write(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}

const mq = (q: string) => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(q) : null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<ThemePref>(() => (read("ds-theme") as ThemePref) || "dark");
  const [systemDark, setSystemDark] = useState(() => mq("(prefers-color-scheme: dark)")?.matches ?? true);
  const [systemReduce, setSystemReduce] = useState(() => mq("(prefers-reduced-motion: reduce)")?.matches ?? false);
  const [motionOverride, setMotionOverride] = useState<boolean | null>(() => {
    const v = read("ds-reduced-motion");
    return v === null ? null : v === "true";
  });

  useEffect(() => {
    const a = mq("(prefers-color-scheme: dark)");
    const b = mq("(prefers-reduced-motion: reduce)");
    const fa = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    const fb = (e: MediaQueryListEvent) => setSystemReduce(e.matches);
    a?.addEventListener?.("change", fa);
    b?.addEventListener?.("change", fb);
    return () => {
      a?.removeEventListener?.("change", fa);
      b?.removeEventListener?.("change", fb);
    };
  }, []);

  const resolved: "dark" | "light" = pref === "system" ? (systemDark ? "dark" : "light") : pref;
  const reducedMotion = motionOverride ?? systemReduce;

  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
  }, [resolved]);
  useEffect(() => {
    document.documentElement.dataset.reducedMotion = String(reducedMotion);
  }, [reducedMotion]);

  const setPref = useCallback((p: ThemePref) => {
    write("ds-theme", p);
    setPrefState(p);
  }, []);
  const setReducedMotion = useCallback((v: boolean | null) => {
    write("ds-reduced-motion", v === null ? null : String(v));
    setMotionOverride(v);
  }, []);

  const value = useMemo(() => ({ pref, resolved, setPref, reducedMotion, setReducedMotion }), [pref, resolved, setPref, reducedMotion, setReducedMotion]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTheme() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useTheme outside ThemeProvider");
  return c;
}
