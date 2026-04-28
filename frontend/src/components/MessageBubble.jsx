import ConfidenceBar from "./ConfidenceBar";

const URGENCE_COLOR = {
  bas: "#22c55e",
  moyen: "#f59e0b",
  haut: "#ef4444",
  critique: "#7c3aed",
};

export default function MessageBubble({ msg }) {
  const isUser = msg.role === "user";
  const state = msg.state || {};
  const hideDetails = Boolean(state.hide_details_in_bubble);

  return (
    <div
      style={{
        display: "flex",
        justifyContent: isUser ? "flex-end" : "flex-start",
        marginBottom: 12,
      }}
    >
      <div
        style={{
          maxWidth: "78%",
          padding: "10px 14px",
          borderRadius: isUser ? "18px 18px 4px 18px" : "18px 18px 18px 4px",
          background: isUser ? "#2563eb" : "#f3f4f6",
          color: isUser ? "#fff" : "#111827",
          fontSize: 14,
          lineHeight: 1.5,
        }}
      >
        <div>{msg.content}</div>
        {!isUser && msg.state && !hideDetails && (
          <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid #d1d5db", fontSize: 12 }}>
            {state.module && <span style={chip("#dbeafe", "#1d4ed8")}>Module: {state.module}</span>}
            {state.software && <span style={chip("#e0f2fe", "#0369a1")}>Logiciel: {state.software}</span>}
            {state.software_version && <span style={chip("#f1f5f9", "#475569")}>Version: {state.software_version}</span>}
            {state.type_incident && <span style={chip("#ede9fe", "#6d28d9")}>Type: {state.type_incident}</span>}
            {state.niveau_urgence && (
              <span
                style={chip(
                  `${URGENCE_COLOR[state.niveau_urgence] || "#6b7280"}22`,
                  URGENCE_COLOR[state.niveau_urgence] || "#6b7280"
                )}
              >
                Urgence: {state.niveau_urgence}
              </span>
            )}
            {state.escalade_necessaire && <span style={chip("#fee2e2", "#dc2626")}>Escalade</span>}
            {state.confidence_score !== undefined && <ConfidenceBar score={state.confidence_score} />}
          </div>
        )}
      </div>
    </div>
  );
}

function chip(bg, fg) {
  return {
    display: "inline-block",
    background: bg,
    color: fg,
    padding: "2px 8px",
    borderRadius: 999,
    marginRight: 6,
    marginBottom: 6,
  };
}
