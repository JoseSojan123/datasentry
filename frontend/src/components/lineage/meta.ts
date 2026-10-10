import { BarChart3, Boxes, Database, Layers, Send, Workflow, type LucideIcon } from "lucide-react";

export const NODE_TYPE: Record<string, { label: string; icon: LucideIcon }> = {
  dataset: { label: "Dataset", icon: Database },
  transformation: { label: "Transformation", icon: Workflow },
  feature_table: { label: "Feature table", icon: Layers },
  model: { label: "Model", icon: Boxes },
  report: { label: "Report", icon: BarChart3 },
  consumer: { label: "Consumer", icon: Send },
};

export const PROVENANCE: Record<string, { label: string; dash: string | undefined; description: string }> = {
  confirmed: { label: "Confirmed", dash: undefined, description: "Observed by DataSentry (e.g. a model registered with this reference dataset)." },
  declared: { label: "Declared", dash: "6 4", description: "Entered by a person; not verified by the platform." },
  inferred: { label: "Inferred", dash: "1.5 4", description: "Suggested by naming or usage; treat as a hypothesis." },
};
