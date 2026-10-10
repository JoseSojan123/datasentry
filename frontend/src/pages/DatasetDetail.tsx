import { useQuery } from "@tanstack/react-query";
import { useParams, useSearchParams } from "react-router-dom";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge, HealthIndicator } from "@/components/ui/Badge";
import { ErrorState, LoadingBlock, Panel, Tabs } from "@/components/ui/primitives";
import { get } from "@/lib/api";
import { fmtRelative } from "@/lib/format";
import type { Dataset } from "@/lib/types";
import { ChecksTab } from "./dataset/ChecksTab";
import { DriftTab } from "./dataset/DriftTab";
import { OverviewTab } from "./dataset/OverviewTab";
import { ProfileTab } from "./dataset/ProfileTab";
import { RulesTab } from "./dataset/RulesTab";
import { SettingsTab } from "./dataset/SettingsTab";
import { VersionsTab } from "./dataset/VersionsTab";

type Tab = "overview" | "profile" | "rules" | "checks" | "versions" | "drift" | "settings";

export default function DatasetDetail() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "overview";
  const q = useQuery({ queryKey: ["dataset", Number(id)], queryFn: () => get<Dataset>(`/datasets/${id}`) });

  if (q.isError)
    return (
      <Panel>
        <ErrorState error={q.error} retry={() => q.refetch()} />
      </Panel>
    );
  if (!q.data) return <LoadingBlock rows={8} label="Loading dataset" />;
  const ds = q.data;

  return (
    <>
      <PageHeader
        title={ds.name}
        crumbs={[{ label: "Datasets", to: "/datasets" }, { label: ds.name }]}
        meta={
          <>
            <HealthIndicator health={ds.health} pulse />
            <span className="text-faint">·</span>
            <Badge tone={ds.criticality === "critical" ? "crit" : ds.criticality === "high" ? "warn" : "neutral"}>{ds.criticality} criticality</Badge>
            {ds.source_type === "synthetic" && <Badge tone="accent">synthetic data</Badge>}
            <span className="text-sm text-faint">
              {ds.version_count} version{ds.version_count === 1 ? "" : "s"} · updated {fmtRelative(ds.updated_at)}
            </span>
          </>
        }
      />
      <Tabs<Tab>
        className="mb-5"
        value={tab}
        onChange={(t) => setParams({ tab: t }, { replace: true })}
        tabs={[
          { id: "overview", label: "Overview" },
          { id: "profile", label: "Profile" },
          { id: "rules", label: "Rules", count: ds.rule_count },
          { id: "checks", label: "Check runs" },
          { id: "versions", label: "Versions", count: ds.version_count },
          { id: "drift", label: "Drift" },
          { id: "settings", label: "Settings" },
        ]}
      />
      {tab === "overview" && <OverviewTab ds={ds} />}
      {tab === "profile" && <ProfileTab ds={ds} />}
      {tab === "rules" && <RulesTab ds={ds} />}
      {tab === "checks" && <ChecksTab ds={ds} />}
      {tab === "versions" && <VersionsTab ds={ds} />}
      {tab === "drift" && <DriftTab ds={ds} />}
      {tab === "settings" && <SettingsTab key={ds.updated_at} ds={ds} />}
    </>
  );
}
