import { Plane } from "../Icons";

export function ResultsPanel(): React.ReactElement {
  return (
    <div
      style={{
        textAlign: "center",
        padding: "40px 20px",
        color: "var(--fg-3)",
        fontSize: 12,
      }}
    >
      <div style={{ marginBottom: 8, opacity: 0.4 }}>
        <Plane size={32} />
      </div>
      <div>No results yet.</div>
      <div style={{ marginTop: 4 }}>Run a query to see flights.</div>
    </div>
  );
}
