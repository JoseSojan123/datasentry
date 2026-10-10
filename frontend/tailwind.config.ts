import type { Config } from "tailwindcss";

const c = (v: string) => `rgb(var(--${v}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: c("bg"),
        surface: c("surface"),
        raised: c("raised"),
        overlay: c("overlay"),
        line: c("border"),
        "line-strong": c("border-strong"),
        fg: c("text"),
        muted: c("muted"),
        faint: c("faint"),
        accent: c("accent"),
        "accent-fg": c("accent-fg"),
        crit: c("crit"),
        warn: c("warn"),
        info: c("info"),
        ok: c("ok"),
        ref: c("ref"),
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "monospace"],
      },
      fontSize: {
        "2xs": ["10.5px", "14px"],
        xs: ["11.5px", "16px"],
        sm: ["12.5px", "18px"],
        base: ["13.5px", "20px"],
        md: ["14.5px", "21px"],
        lg: ["16px", "23px"],
        xl: ["19px", "26px"],
        "2xl": ["24px", "30px"],
        "3xl": ["32px", "38px"],
        "4xl": ["44px", "50px"],
      },
      borderRadius: { sm: "4px", DEFAULT: "6px", md: "7px", lg: "9px", xl: "12px" },
      boxShadow: {
        panel: "0 1px 0 0 rgb(var(--shadow) / 0.04), 0 1px 2px 0 rgb(var(--shadow) / 0.25)",
        pop: "0 12px 32px -8px rgb(var(--shadow) / 0.55), 0 0 0 1px rgb(var(--border) / 1)",
      },
      keyframes: {
        shimmer: { "100%": { transform: "translateX(100%)" } },
        "pulse-ring": { "0%": { transform: "scale(0.8)", opacity: "0.7" }, "100%": { transform: "scale(2.2)", opacity: "0" } },
        dash: { to: { strokeDashoffset: "-20" } },
      },
      animation: {
        shimmer: "shimmer 1.6s infinite",
        "pulse-ring": "pulse-ring 1.8s cubic-bezier(0.2,0.6,0.4,1) infinite",
        dash: "dash 0.9s linear infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
