import { Play } from "../Icons";

export function QueryBuilderFooter(): React.ReactElement {
  return (
    <button
      style={{
        width: "100%",
        background: "var(--accent)",
        color: "#fff",
        border: 0,
        padding: "9px 12px",
        borderRadius: "var(--radius-2)",
        fontSize: 13,
        fontWeight: 600,
        cursor: "pointer",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 8,
        fontFamily: "inherit",
        letterSpacing: "-0.005em",
        opacity: 0.5,
      }}
      disabled
    >
      <Play /> Run query
    </button>
  );
}

export function QueryBuilderBody(): React.ReactElement {
  return (
    <div style={{ color: "var(--fg-3)", fontSize: 12, textAlign: "center", paddingTop: 32 }}>
      <div style={{ marginBottom: 8, opacity: 0.4 }}>
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="11" cy="11" r="8" />
          <path d="M21 21l-4.35-4.35" />
        </svg>
      </div>
      <div>No filters yet.</div>
      <div style={{ marginTop: 4, color: "var(--fg-3)" }}>Add a filter to get started.</div>
    </div>
  );
}
