import { ExternalLink } from "lucide-react";
import { useState } from "react";
import { CodeBlock } from "@/components/common/Json";
import { PageHeader } from "@/components/layout/PageHeader";
import { Callout, Panel } from "@/components/ui/primitives";
import { API_URL } from "@/lib/api";
import { cn } from "@/lib/cn";

const SECTIONS = [
  { id: "start", title: "Getting started" },
  { id: "concepts", title: "Concepts" },
  { id: "methods", title: "How detection works" },
  { id: "sdk", title: "Python SDK" },
  { id: "rest", title: "REST API" },
  { id: "limits", title: "Limitations" },
];

const SDK = `pip install ./sdk          # from the repository

from datasentry import DataSentry
import pandas as pd

client = DataSentry(api_url="${typeof window !== "undefined" ? window.location.origin : "http://localhost:8000"}", api_key="dsk_...")

df = pd.read_csv("orders.csv")
dataset = client.register_dataset(name="orders", data=df, owner="analytics")

client.add_rule(dataset.id, "not_null", columns=["order_id"], severity="critical")
client.add_rule(dataset.id, "range", columns=["amount"], config={"min": 0})

version, monitoring = client.create_version(dataset.id, pd.read_csv("orders_today.csv"))
print(monitoring.status, monitoring.findings)
if monitoring.incident_id:
    print(client.get_incident(monitoring.incident_id).priority)`;

const CURL = `curl -s -H "X-API-Key: $DATASENTRY_API_KEY" \\
  ${API_URL || "https://your-deployment"}/api/v1/incidents?status=open&sort=priority`;

function H({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <h2 id={id} className="scroll-mt-20 text-xl font-semibold tracking-tight">
      {children}
    </h2>
  );
}

export default function Docs() {
  const [active, setActive] = useState("start");
  return (
    <>
      <PageHeader title="Docs & SDK" description="How DataSentry decides what is a problem, and how to send it data." />
      <div className="grid gap-6 lg:grid-cols-[200px_minmax(0,1fr)]">
        <nav aria-label="Documentation sections" className="lg:sticky lg:top-20 lg:self-start">
          <ul className="flex gap-1 overflow-x-auto lg:flex-col">
            {SECTIONS.map((s) => (
              <li key={s.id}>
                <a href={`#${s.id}`} onClick={() => setActive(s.id)} className={cn("block whitespace-nowrap rounded px-2.5 py-1.5 text-base", active === s.id ? "bg-overlay text-fg" : "text-muted hover:text-fg")}>
                  {s.title}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <div className="min-w-0 space-y-10 text-base leading-relaxed text-muted [&_strong]:text-fg">
          <section className="space-y-3">
            <H id="start">Getting started</H>
            <ol className="list-decimal space-y-1.5 pl-5">
              <li>
                <strong>Add a dataset.</strong> Upload a CSV or Parquet file, or push a DataFrame with the SDK. The first version becomes the reference.
              </li>
              <li>
                <strong>Add rules</strong> for the guarantees consumers depend on: keys present and unique, allowed values, ranges, freshness.
              </li>
              <li>
                <strong>Declare lineage</strong> for what reads the dataset, so incidents can show what they put at risk.
              </li>
              <li>
                <strong>Send new versions.</strong> Each one is profiled, validated, compared and tested for drift. Problems open an incident with remediation proposals.
              </li>
              <li>
                <strong>Schedule jobs</strong> on the Jobs page to re-check data that changes without new uploads, or to evaluate models daily.
              </li>
            </ol>
          </section>

          <section className="space-y-3">
            <H id="concepts">Concepts</H>
            <dl className="grid gap-4 sm:grid-cols-2">
              {[
                ["Version", "An immutable snapshot of a dataset. Remediations that change data write a new derived version; originals are never modified."],
                ["Reference version", "The version that later versions are compared against for schema changes and drift. The first upload by default."],
                ["Finding", "One detected problem with its evidence: a failed rule, a schema or profile change, a drifted feature, or a model signal."],
                ["Incident", "Findings for the same dataset or model, grouped and deduplicated. It re-opens if the same problems return within 7 days."],
                ["Priority", "A transparent score from severity, downstream reach, models and reports affected, and source criticality, mapped to P1–P4."],
                ["Confirmed vs declared vs inferred", "Lineage edges observed by the platform are confirmed. Edges people enter are declared; suggested ones are inferred. Impact through any non-confirmed edge is shown as potential."],
                ["Verification", "After a remediation runs, the checks that raised the incident are run again on the active version. Only if they pass is the incident resolved as verified."],
                ["Validation gate", "Per dataset. In block mode a version with critical findings is quarantined and the previous version stays active."],
              ].map(([t, d]) => (
                <div key={t} className="panel p-4">
                  <dt className="font-medium text-fg">{t}</dt>
                  <dd className="mt-1 text-sm">{d}</dd>
                </div>
              ))}
            </dl>
          </section>

          <section className="space-y-3">
            <H id="methods">How detection works</H>
            <p>
              <strong>Numeric drift</strong> uses the Population Stability Index on reference-quantile bins (10 by default, +0.5 smoothing) for effect size, and the two-sample Kolmogorov–Smirnov test for significance. <strong>Categorical drift</strong> uses Jensen–Shannon distance (base 2) and the chi-square test of homogeneity, pooling sparse categories so expected counts stay valid.
            </p>
            <p>
              p-values across all features in one evaluation are corrected with Benjamini–Hochberg by default. A feature is reported as <strong>drift</strong> only when the effect size reaches the warning threshold <em>and</em> the corrected test is significant. A large effect without significance is <strong>inconclusive</strong>; a significant but tiny effect is noted but not flagged. With large samples almost any difference is significant, so effect size matters.
            </p>
            <p>
              <strong>Model performance</strong> is compared with the registered baseline using a 95% bootstrap interval (300 resamples). Degradation is reported only when the whole interval is worse than the baseline by more than the tolerance (5% relative by default); otherwise a drop is inconclusive. Input drift, prediction drift and performance are reported separately: drift alone does not prove a model got worse.
            </p>
            <p>
              <strong>Profiling</strong> flags outliers with Tukey fences (k = 1.5), rare categories below 1% of rows, time gaps longer than 1.5× the typical interval, and staleness from a freshness column.
            </p>
            <Callout tone="neutral">The full methodology with formulas and the benchmark results are in docs/methodology.md and docs/benchmark.md in the repository.</Callout>
          </section>

          <section className="space-y-3">
            <H id="sdk">Python SDK</H>
            <p>Create an API key under Settings, then:</p>
            <CodeBlock code={SDK} language="python" />
            <p>
              Model monitoring: <code className="font-mono text-sm text-fg">register_model</code>, <code className="font-mono text-sm text-fg">create_model_version</code>, <code className="font-mono text-sm text-fg">log_predictions</code>, <code className="font-mono text-sm text-fg">log_labels</code> (labels may arrive later), then <code className="font-mono text-sm text-fg">evaluate_model</code>. Choose <code className="font-mono text-sm">feature_logging</code> per version: <code className="font-mono text-sm">none</code>, <code className="font-mono text-sm">aggregate</code> (histograms only) or <code className="font-mono text-sm">full</code>.
            </p>
          </section>

          <section className="space-y-3">
            <H id="rest">REST API</H>
            <p>
              Every feature in this interface is available under <code className="font-mono text-sm text-fg">/api/v1</code>. Authenticate with a bearer token from sign-in or an <code className="font-mono text-sm text-fg">X-API-Key</code> header. Errors share one shape: <code className="font-mono text-sm">{"{ error: { code, message, details, request_id } }"}</code>.
            </p>
            <CodeBlock code={CURL} language="shell" />
            <a href={`${API_URL}/api/docs`} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-1">
              Interactive API reference <ExternalLink className="h-3.5 w-3.5" />
            </a>
          </section>

          <section className="space-y-3">
            <H id="limits">Limitations</H>
            <ul className="list-disc space-y-1.5 pl-5">
              <li>Files are limited to 25 MB and 500,000 rows per version by default, and are processed in memory.</li>
              <li>Drift tests assume rows are independent samples. Strong seasonality or autocorrelation can make significance overstated; compare like-for-like windows.</li>
              <li>Rename detection is a suggestion based on names, profiles and position. It needs a person to confirm it.</li>
              <li>Lineage is only as complete as what is declared. Missing edges mean impact is under-reported, which is why unknown reach is stated rather than assumed to be zero.</li>
              <li>Business impact is qualitative unless you configure your own cost assumptions per consumer.</li>
              <li>The rate limiter is per process. Behind several API replicas, limits apply per replica.</li>
            </ul>
          </section>
          <Panel title="Need help?">
            <p className="text-sm">Every finding links to its evidence. If a result looks wrong, the evidence panel shows the inputs, thresholds and sample sizes used, so you can check it or adjust the dataset's thresholds.</p>
          </Panel>
        </div>
      </div>
    </>
  );
}
