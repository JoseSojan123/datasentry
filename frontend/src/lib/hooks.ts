import { useEffect, useState } from "react";

export function useDocumentTitle(title: string | undefined) {
  useEffect(() => {
    document.title = title ? `${title} · DataSentry` : "DataSentry";
  }, [title]);
}

export function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function useMediaQuery(q: string): boolean {
  const [m, setM] = useState(() => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(q).matches : false));
  useEffect(() => {
    if (!window.matchMedia) return;
    const mql = window.matchMedia(q);
    const f = () => setM(mql.matches);
    f();
    mql.addEventListener?.("change", f);
    return () => mql.removeEventListener?.("change", f);
  }, [q]);
  return m;
}
