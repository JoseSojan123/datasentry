const nf = new Intl.NumberFormat("en-US");
const dtf = new Intl.DateTimeFormat("en-GB", { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false, timeZoneName: "short" });
const df = new Intl.DateTimeFormat("en-GB", { month: "short", day: "2-digit" });

export const fmtInt = (n: number | null | undefined) => (n === null || n === undefined ? "—" : nf.format(Math.round(n)));

export function fmtNum(n: number | null | undefined, digits = 3): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (abs !== 0 && (abs < 0.001 || abs >= 1e7)) return n.toExponential(2);
  if (Number.isInteger(n)) return nf.format(n);
  return Number(n.toFixed(digits)).toLocaleString("en-US", { maximumFractionDigits: digits });
}

export const fmtPct = (n: number | null | undefined, digits = 1) => (n === null || n === undefined ? "—" : `${n.toFixed(digits)}%`);
export const fmtFrac = (n: number | null | undefined, digits = 0) => (n === null || n === undefined ? "—" : `${(n * 100).toFixed(digits)}%`);

export function fmtP(p: number | null | undefined): string {
  if (p === null || p === undefined) return "n/a";
  if (p < 1e-4) return "< 0.0001";
  return p.toFixed(4);
}

export function fmtBytes(b: number | null | undefined): string {
  if (!b && b !== 0) return "—";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = b;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i ? 1 : 0)} ${u[i]}`;
}

export function fmtDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  const m = s / 60;
  if (m < 60) return `${m.toFixed(1)} min`;
  const h = m / 60;
  if (h < 48) return `${h.toFixed(1)} h`;
  return `${(h / 24).toFixed(1)} d`;
}

export const fmtSeconds = (s: number | null | undefined) => (s === null || s === undefined ? "—" : fmtDuration(s * 1000));

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return dtf.format(new Date(iso));
}

export function fmtDay(iso: string | null | undefined): string {
  if (!iso) return "—";
  return df.format(new Date(iso));
}

export function fmtRelative(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const diff = (new Date(iso).getTime() - now) / 1000;
  const abs = Math.abs(diff);
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  if (abs < 45) return diff < 0 ? "just now" : "in a moment";
  if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
  if (abs < 86400 * 30) return rtf.format(Math.round(diff / 86400), "day");
  return fmtDate(iso);
}

export const humanize = (s: string | null | undefined) => (s ?? "").replace(/_/g, " ");

export function cap(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}
