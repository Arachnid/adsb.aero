interface SidebarProps {
  side: "left" | "right";
  collapsed: boolean;
  title: string;
  meta?: string;
  toolbar?: React.ReactNode;
  footer?: React.ReactNode;
  children: React.ReactNode;
}

export function Sidebar({
  side,
  collapsed,
  title,
  meta,
  toolbar,
  footer,
  children,
}: SidebarProps): React.ReactElement {
  const isLeft = side === "left";

  return (
    <div
      style={{
        position: "absolute",
        top: 12,
        bottom: 12,
        width: 340,
        [isLeft ? "left" : "right"]: 12,
        background: "color-mix(in oklab, var(--bg-1) 94%, transparent)",
        backdropFilter: "blur(14px)",
        WebkitBackdropFilter: "blur(14px)",
        border: "1px solid var(--line-1)",
        borderRadius: "var(--radius-3)",
        boxShadow: "var(--shadow-2)",
        zIndex: 9,
        display: "flex",
        flexDirection: "column",
        transition: "transform 240ms cubic-bezier(0.4, 0, 0.2, 1)",
        transform: collapsed
          ? `translateX(${isLeft ? "calc(-100% - 18px)" : "calc(100% + 18px)"})`
          : "none",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "12px 14px 10px",
          borderBottom: "1px solid var(--line-1)",
          flexShrink: 0,
        }}
      >
        <span
          style={{
            fontSize: 11,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            color: "var(--fg-2)",
            fontWeight: 600,
          }}
        >
          {title}
        </span>
        {meta !== undefined && (
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 10.5,
              color: "var(--fg-3)",
            }}
          >
            {meta}
          </span>
        )}
      </div>

      <div className="sb-scroll" style={{ flex: 1, overflowY: "auto", padding: "10px 12px" }}>
        {children}
      </div>

      {toolbar !== undefined && (
        <div style={{ flexShrink: 0, padding: "0 12px 10px", position: "relative" }}>
          {toolbar}
        </div>
      )}

      {footer !== undefined && (
        <div
          style={{
            flexShrink: 0,
            padding: "10px 12px",
            borderTop: "1px solid var(--line-1)",
            background: "color-mix(in oklab, var(--bg-2) 50%, transparent)",
          }}
        >
          {footer}
        </div>
      )}
    </div>
  );
}
