import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AboutDialog } from "../src/components/ui/AboutDialog";

describe("AboutDialog", () => {
  it("renders nothing when closed", () => {
    const { container } = render(
      <AboutDialog open={false} onClose={() => undefined} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders content when open", () => {
    render(<AboutDialog open={true} onClose={() => undefined} />);
    expect(screen.getByText("adsb.aero")).toBeInTheDocument();
    expect(screen.getByText("Historical flight explorer")).toBeInTheDocument();
    expect(screen.getByText("Pressure-corrected altitude")).toBeInTheDocument();
    expect(screen.getByText("Flexible queries")).toBeInTheDocument();
    expect(screen.getByText("Rich visualisation")).toBeInTheDocument();
    expect(screen.getByText("Airspace overlay")).toBeInTheDocument();
    expect(screen.getByText("Data sources")).toBeInTheDocument();
    expect(screen.getAllByText("adsb.lol").length).toBeGreaterThan(0);
    expect(screen.getByText("NOAA GFS")).toBeInTheDocument();
    expect(screen.getByText("OpenAIP")).toBeInTheDocument();
    expect(screen.getByText("Source code")).toBeInTheDocument();
  });

  it("calls onClose when the close button is clicked", () => {
    const onClose = vi.fn();
    render(<AboutDialog open={true} onClose={onClose} />);
    fireEvent.click(screen.getByLabelText("Close"));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("calls onClose when the backdrop is clicked", () => {
    const onClose = vi.fn();
    render(<AboutDialog open={true} onClose={onClose} />);
    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("does not call onClose when the card itself is clicked", () => {
    const onClose = vi.fn();
    render(<AboutDialog open={true} onClose={onClose} />);
    fireEvent.click(screen.getByText("Pressure-corrected altitude"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("calls onClose on Escape key", () => {
    const onClose = vi.fn();
    render(<AboutDialog open={true} onClose={onClose} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("does not call onClose on other keys", () => {
    const onClose = vi.fn();
    render(<AboutDialog open={true} onClose={onClose} />);
    fireEvent.keyDown(document, { key: "Enter" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("links to the GitHub source", () => {
    render(<AboutDialog open={true} onClose={() => undefined} />);
    const link = screen.getByText("github.com/Arachnid/adsb.aero");
    expect(link).toHaveAttribute(
      "href",
      "https://github.com/Arachnid/adsb.aero",
    );
  });
});
