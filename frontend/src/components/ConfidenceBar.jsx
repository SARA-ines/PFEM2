export default function ConfidenceBar({ score = 0 }) {
  const pct = Math.round(score * 100);
  const color = pct > 75 ? "#22c55e" : pct > 55 ? "#f59e0b" : "#ef4444";

  return (
    <div style={{ marginTop: 6, fontSize: 11, color: "#6b7280" }}>
      Confiance : {pct}%
      <div style={{ background: "#e5e7eb", borderRadius: 4, height: 4, marginTop: 2 }}>
        <div
          style={{
            width: `${pct}%`,
            background: color,
            height: 4,
            borderRadius: 4,
            transition: "width 0.4s",
          }}
        />
      </div>
    </div>
  );
}
