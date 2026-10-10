import { describe, expect, it } from "vitest";
import { dailyPivot } from "@/components/charts/TrendChart";
import { toneFor } from "@/components/ui/Badge";
import { validateFile } from "@/components/common/Dropzone";
import { qs } from "@/lib/api";
import { fmtBytes, fmtDuration, fmtFrac, fmtInt, fmtNum, fmtP, fmtPct, humanize } from "@/lib/format";

describe("format", () => {
  it("formats numbers without inventing precision", () => {
    expect(fmtInt(1234567)).toBe("1,234,567");
    expect(fmtInt(null)).toBe("—");
    expect(fmtNum(0.123456)).toBe("0.123");
    expect(fmtNum(0.00001)).toBe("1.00e-5");
    expect(fmtNum(undefined)).toBe("—");
    expect(fmtPct(32)).toBe("32.0%");
    expect(fmtFrac(0.4567)).toBe("46%");
  });
  it("reports tiny p-values as a bound", () => {
    expect(fmtP(2.6e-99)).toBe("< 0.0001");
    expect(fmtP(0.0312)).toBe("0.0312");
    expect(fmtP(null)).toBe("n/a");
  });
  it("formats bytes and durations", () => {
    expect(fmtBytes(512)).toBe("512 B");
    expect(fmtBytes(176271)).toBe("172.1 KB");
    expect(fmtDuration(238.6)).toBe("239 ms");
    expect(fmtDuration(90_000)).toBe("1.5 min");
    expect(humanize("null_pct_increase_large")).toBe("null pct increase large");
  });
  it("builds query strings and drops empty values", () => {
    expect(qs({ a: 1, b: "", c: null, d: undefined, e: "x y" })).toBe("?a=1&e=x+y");
    expect(qs({})).toBe("");
  });
});

describe("toneFor", () => {
  it("maps states to semantic tones", () => {
    expect(toneFor("critical")).toBe("crit");
    expect(toneFor("inconclusive")).toBe("warn");
    expect(toneFor("verified")).toBe("ok");
    expect(toneFor("something-else")).toBe("neutral");
  });
});

describe("validateFile", () => {
  const file = (name: string, size: number) => new File([new Uint8Array(size)], name);
  it("accepts csv and parquet", () => {
    expect(validateFile(file("a.csv", 10))).toBeNull();
    expect(validateFile(file("a.parquet", 10))).toBeNull();
  });
  it("rejects other types, empty and oversized files", () => {
    expect(validateFile(file("a.xlsx", 10))).toMatch(/not supported/);
    expect(validateFile(file("a.csv", 0))).toMatch(/empty/);
    const big = { name: "big.csv", size: 26 * 1024 * 1024 } as File;
    expect(validateFile(big)).toMatch(/limit is 25 MB/);
  });
});

describe("dailyPivot", () => {
  it("fills missing days with zero-height rows and sums by key", () => {
    const today = new Date().toISOString().slice(0, 10);
    const rows = dailyPivot([{ day: today, severity: "critical", count: 2 }, { day: today, severity: "critical", count: 1 }, { day: "1999-01-01", severity: "warning", count: 9 }], "severity", 7);
    expect(rows).toHaveLength(7);
    expect(rows[6]).toEqual({ day: today, critical: 3 });
    expect(rows.slice(0, 6).every((r) => Object.keys(r).length === 1)).toBe(true);
  });
});
