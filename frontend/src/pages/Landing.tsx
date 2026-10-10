import { motion } from "framer-motion";
import { ArrowRight, CheckCircle2, GitBranch, ListChecks, ShieldCheck, Waves } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Logo } from "@/components/layout/Logo";
import { Button, ButtonLink } from "@/components/ui/Button";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useDocumentTitle } from "@/lib/hooks";
import { useMotion } from "@/lib/motion";

const STAGES = [
  { icon: ListChecks, title: "Detect", body: "Profiles every version, runs 11 rule types, compares schemas and tests drift with PSI, KS, JS distance and chi-square, corrected for multiple testing." },
  { icon: GitBranch, title: "Trace impact", body: "Walks the lineage graph from the failing dataset and separates confirmed dependencies from declared or inferred ones." },
  { icon: ShieldCheck, title: "Remediate safely", body: "Proposes reversible actions with preconditions and rollback. Nothing destructive; data changes always write a new version." },
  { icon: CheckCircle2, title: "Verify", body: "An incident is only marked resolved after the checks that raised it pass again, or a person resolves it with a note." },
];

/** Illustrative lineage: the shapes are a diagram, not data. */
function HeroDiagram() {
  const { reduced } = useMotion();
  const nodes = [
    { x: 20, y: 120, label: "card_transactions", tone: "crit" },
    { x: 220, y: 120, label: "clean_transactions", tone: "crit" },
    { x: 420, y: 40, label: "spend_features", tone: "crit" },
    { x: 420, y: 200, label: "revenue_dashboard", tone: "warn" },
    { x: 600, y: 40, label: "churn_model", tone: "warn" },
  ];
  const edges: [number, number, string?][] = [
    [0, 1],
    [1, 2],
    [1, 3, "6 4"],
    [2, 4, "1.5 4"],
  ];
  const col = (t: string) => (t === "crit" ? "rgb(var(--crit))" : "rgb(var(--warn))");
  return (
    <svg viewBox="0 0 760 280" className="h-auto w-full" role="img" aria-label="Illustration: a failing dataset propagating impact through a transformation to a feature table, a dashboard and a model.">
      {edges.map(([a, b, dash], i) => {
        const A = nodes[a];
        const B = nodes[b];
        const x1 = A.x + 150;
        const y1 = A.y + 22;
        const x2 = B.x;
        const y2 = B.y + 22;
        const mx = (x1 + x2) / 2;
        return (
          <motion.path
            key={i}
            d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`}
            fill="none"
            stroke={col(nodes[b].tone)}
            strokeWidth={1.8}
            strokeDasharray={dash ?? "5 5"}
            initial={reduced ? false : { pathLength: 0, opacity: 0 }}
            animate={{ pathLength: 1, opacity: 0.9 }}
            transition={{ delay: reduced ? 0 : 0.4 + i * 0.25, duration: reduced ? 0 : 0.6 }}
            className={reduced ? undefined : "animate-dash"}
          />
        );
      })}
      {nodes.map((n, i) => (
        <motion.g key={i} initial={reduced ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: reduced ? 0 : 0.15 + i * 0.22, duration: reduced ? 0 : 0.4 }}>
          <rect x={n.x} y={n.y} width={150} height={44} rx={8} fill="rgb(var(--surface))" stroke={col(n.tone)} strokeOpacity={i === 0 ? 1 : 0.7} strokeWidth={i === 0 ? 1.6 : 1.2} />
          <circle cx={n.x + 16} cy={n.y + 22} r={4} fill={col(n.tone)} />
          <text x={n.x + 28} y={n.y + 26.5} fill="rgb(var(--text))" fontSize="12" fontFamily="IBM Plex Mono, monospace">
            {n.label}
          </text>
        </motion.g>
      ))}
    </svg>
  );
}

export default function Landing() {
  useDocumentTitle(undefined);
  const { status, startDemo } = useAuth();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const { fadeUp, stagger } = useMotion();

  const demo = async () => {
    setBusy(true);
    try {
      await startDemo(true);
      navigate("/overview");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not start the demo.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen overflow-x-hidden bg-bg">
      <header className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
        <Logo />
        <nav className="flex items-center gap-2">
          {status === "authenticated" ? (
            <ButtonLink to="/overview" variant="primary" size="sm">
              Open console
            </ButtonLink>
          ) : (
            <>
              <ButtonLink to="/login" variant="ghost" size="sm">
                Sign in
              </ButtonLink>
              <ButtonLink to="/register" size="sm" className="hidden sm:inline-flex">
                Create account
              </ButtonLink>
            </>
          )}
        </nav>
      </header>

      <main>
        <section className="relative">
          <div className="pointer-events-none absolute inset-0 grid-bg [mask-image:radial-gradient(ellipse_at_top,black_20%,transparent_70%)]" aria-hidden />
          <motion.div variants={stagger} initial="hidden" animate="show" className="relative mx-auto grid max-w-6xl gap-10 px-4 pb-16 pt-10 sm:px-6 sm:pt-16 lg:grid-cols-[1.05fr_1fr] lg:items-center">
            <div>
              <motion.div variants={fadeUp} className="mb-4 inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-sm text-muted">
                <span className="h-1.5 w-1.5 rounded-full bg-accent" /> Open-source data quality and ML monitoring
              </motion.div>
              <motion.h1 variants={fadeUp} className="text-3xl font-semibold leading-[1.1] tracking-tight text-fg sm:text-4xl">
                Find bad data, see what it breaks downstream, and <span className="text-accent">prove the fix worked</span>.
              </motion.h1>
              <motion.p variants={fadeUp} className="mt-4 max-w-xl text-md text-muted">
                DataSentry checks every dataset version and model window for quality failures, schema changes and drift, ranks incidents by their lineage impact, and only closes them after verification.
              </motion.p>
              <motion.div variants={fadeUp} className="mt-7 flex flex-wrap gap-2.5">
                <Button variant="primary" size="lg" onClick={demo} loading={busy} icon={!busy ? <Waves className="h-4 w-4" /> : undefined}>
                  Explore the live demo
                </Button>
                <ButtonLink to="/register" size="lg" variant="outline">
                  Start with your data <ArrowRight className="h-4 w-4" />
                </ButtonLink>
              </motion.div>
              <motion.p variants={fadeUp} className="mt-3 text-sm text-faint">
                The demo creates a private workspace with synthetic, labelled data. It expires automatically.
              </motion.p>
            </div>
            <motion.div variants={fadeUp} className="panel p-4 sm:p-5">
              <div className="mb-3 flex items-center justify-between">
                <span className="label">Incident impact path</span>
                <span className="text-2xs text-faint">illustration</span>
              </div>
              <HeroDiagram />
            </motion.div>
          </motion.div>
        </section>

        <section className="border-t border-line bg-surface/50">
          <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
            <h2 className="text-xl font-semibold tracking-tight">How an incident moves through DataSentry</h2>
            <ol className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {STAGES.map((s, i) => (
                <li key={s.title} className="panel relative p-4">
                  <div className="mb-3 flex items-center gap-2">
                    <span className="font-mono text-xs text-faint">0{i + 1}</span>
                    <s.icon className="h-4 w-4 text-accent" aria-hidden />
                    <h3 className="text-md font-medium">{s.title}</h3>
                  </div>
                  <p className="text-sm leading-relaxed text-muted">{s.body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
          <div className="grid gap-8 lg:grid-cols-3">
            <div>
              <h2 className="text-xl font-semibold tracking-tight">Built to be honest about uncertainty</h2>
              <p className="mt-2 text-base text-muted">Statistical findings show their evidence, sample sizes and thresholds, so a reviewer can disagree with them.</p>
            </div>
            <ul className="grid gap-3 text-base text-muted sm:grid-cols-2 lg:col-span-2">
              {[
                "Drift is flagged only when the effect size crosses a threshold and the corrected test is significant; otherwise it is reported as inconclusive.",
                "Model degradation uses a bootstrap interval, so a noisy day with few labels is not called a regression.",
                "Input drift, prediction drift and performance are separate signals with delayed labels handled explicitly.",
                "Rename candidates in schema changes need a person to confirm them.",
                "Business impact is described qualitatively unless you configure your own cost assumptions.",
                "Prediction logging can be set to none, aggregate histograms, or full records, with a retention period.",
              ].map((t) => (
                <li key={t} className="flex gap-2.5">
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ok" aria-hidden />
                  {t}
                </li>
              ))}
            </ul>
          </div>
        </section>
      </main>
      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-6 text-sm text-faint sm:px-6">
          <span>DataSentry · MIT licensed</span>
          <span className="flex gap-4">
            <Link to="/login" className="hover:text-fg">
              Sign in
            </Link>
            <a href="/api/docs" className="hover:text-fg">
              API reference
            </a>
          </span>
        </div>
      </footer>
    </div>
  );
}
