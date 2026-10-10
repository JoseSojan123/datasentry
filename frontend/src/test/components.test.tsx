import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { HealthIndicator, SeverityBadge, UrgencyTag } from "@/components/ui/Badge";
import { Dropzone } from "@/components/common/Dropzone";
import { Tabs } from "@/components/ui/primitives";
import { ThemeProvider } from "@/lib/theme";

describe("badges", () => {
  it("labels severity and health in words, not colour alone", () => {
    render(
      <>
        <SeverityBadge severity="critical" />
        <HealthIndicator health="unknown" />
        <UrgencyTag urgency="P1" score={83.2} />
      </>,
    );
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByText("Not checked")).toBeInTheDocument();
    expect(screen.getByTitle("Priority score 83.2 / 100")).toHaveTextContent("P183");
  });
});

describe("Tabs", () => {
  it("supports arrow-key navigation", async () => {
    const onChange = vi.fn();
    render(
      <ThemeProvider>
        <Tabs value="a" onChange={onChange} tabs={[{ id: "a", label: "A" }, { id: "b", label: "B" }]} />
      </ThemeProvider>,
    );
    const a = screen.getByRole("tab", { name: "A" });
    expect(a).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(a, { key: "ArrowRight" });
    expect(onChange).toHaveBeenCalledWith("b");
  });
});

describe("Dropzone", () => {
  it("shows a validation error for unsupported files and does not accept them", async () => {
    const onFile = vi.fn();
    const { container } = render(<Dropzone file={null} onFile={onFile} />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File(["x"], "data.xlsx"), { applyAccept: false });
    expect(await screen.findByRole("alert")).toHaveTextContent(/not supported/);
    expect(onFile).toHaveBeenCalledWith(null);
  });
  it("accepts a CSV", async () => {
    const onFile = vi.fn();
    const { container } = render(<Dropzone file={null} onFile={onFile} />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const f = new File(["a,b\n1,2"], "data.csv", { type: "text/csv" });
    await userEvent.upload(input, f);
    expect(onFile).toHaveBeenCalledWith(f);
  });
});
