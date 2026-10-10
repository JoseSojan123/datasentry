import { Compass } from "lucide-react";
import { ButtonLink } from "@/components/ui/Button";
import { EmptyState, Panel } from "@/components/ui/primitives";
import { useDocumentTitle } from "@/lib/hooks";

export default function NotFound() {
  useDocumentTitle("Not found");
  return (
    <Panel className="mt-6">
      <EmptyState icon={<Compass className="h-5 w-5" />} title="This page does not exist" action={<ButtonLink to="/overview" variant="primary">Go to overview</ButtonLink>}>
        The link may be out of date, or the item was deleted.
      </EmptyState>
    </Panel>
  );
}
