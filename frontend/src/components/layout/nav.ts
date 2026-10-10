import type { LucideIcon } from "lucide-react";
import { Activity, BookOpen, Boxes, CalendarClock, Database, GitBranch, LayoutDashboard, Settings, ShieldAlert, Waves, Wrench } from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  key: string;
}

export const NAV: { group: string; items: NavItem[] }[] = [
  {
    group: "Monitor",
    items: [
      { to: "/overview", label: "Overview", icon: LayoutDashboard, key: "g o" },
      { to: "/incidents", label: "Incidents", icon: ShieldAlert, key: "g i" },
      { to: "/datasets", label: "Datasets", icon: Database, key: "g d" },
      { to: "/drift", label: "Drift", icon: Waves, key: "g f" },
      { to: "/models", label: "Models", icon: Boxes, key: "g m" },
      { to: "/lineage", label: "Lineage", icon: GitBranch, key: "g l" },
    ],
  },
  {
    group: "Operate",
    items: [
      { to: "/remediation", label: "Remediation", icon: Wrench, key: "g r" },
      { to: "/jobs", label: "Jobs", icon: CalendarClock, key: "g j" },
      { to: "/activity", label: "Activity", icon: Activity, key: "g a" },
    ],
  },
  {
    group: "Workspace",
    items: [
      { to: "/settings", label: "Settings", icon: Settings, key: "g s" },
      { to: "/docs", label: "Docs & SDK", icon: BookOpen, key: "g h" },
    ],
  },
];

export const NAV_ITEMS: NavItem[] = NAV.flatMap((g) => g.items);
