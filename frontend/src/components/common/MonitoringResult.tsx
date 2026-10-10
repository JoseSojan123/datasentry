import { CheckCircle2, ShieldAlert } from "lucide-react";
import { Link } from "react-router-dom";
import { Callout } from "@/components/ui/primitives";
import type { Finding } from "@/lib/types";
import { FindingList } from "./Findings";

export interface MonitoringOutcome {
  status: string;
  findings: Finding[];
  incident_id: number | null;
  incident_created?: boolean;
  drift_evaluation_id?: number | null;
  comparison_id?: number | null;
}

export function MonitoringResult({ result, datasetId }: { result: MonitoringOutcome; datasetId: number }) {
  const n = result.findings.length;
  if (result.status === "ingestion_failed") {
    return (
      <Callout tone="crit" icon={<ShieldAlert className="h-4 w-4" />} title="Ingestion failed">
        {result.findings[0]?.message ?? "The file could not be parsed."} The original file was kept so ingestion can be retried.
      </Callout>
    );
  }
  return (
    <div className="space-y-3">
      {n === 0 ? (
        <Callout tone="ok" icon={<CheckCircle2 className="h-4 w-4" />} title="No problems found">
          Profiling, rules{result.drift_evaluation_id ? ", drift" : ""} and schema checks passed on this version.
        </Callout>
      ) : (
        <Callout
          tone={result.status === "critical" ? "crit" : "warn"}
          icon={<ShieldAlert className="h-4 w-4" />}
          title={`${n} finding${n === 1 ? "" : "s"} on this version`}
        >
          {result.incident_id ? (
            <>
              {result.incident_created === false ? "Added to an existing incident. " : "An incident was opened. "}
              <Link to={`/incidents/${result.incident_id}`} className="link">
                Open the investigation
              </Link>
            </>
          ) : (
            "Informational only; no incident was opened."
          )}
        </Callout>
      )}
      {n > 0 && (
        <div className="overflow-hidden rounded-md border border-line">
          <FindingList findings={result.findings} datasetId={datasetId} />
        </div>
      )}
    </div>
  );
}
