export default function TicketCard({ ticket }) {
  if ((ticket.similarity || 0) < 0.25) {
    return null;
  }

  return (
    <div
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 12,
        padding: 12,
        background: "#ffffff",
        marginTop: 8,
      }}
    >
      <div style={{ fontSize: 12, fontWeight: 700, color: "#1f2937" }}>
        {ticket.id || "Ticket"} - {ticket.module || "inconnu"} / {ticket.type || "inconnu"}
      </div>
      {ticket.selectedModule && (
        <div style={{ fontSize: 12, color: "#374151", marginTop: 6 }}>
          Module choisi : {ticket.selectedModule}
        </div>
      )}
      <div style={{ fontSize: 13, color: "#374151", marginTop: 6 }}>{ticket.description}</div>
      {ticket.solution && (
        <div style={{ fontSize: 12, color: "#111827", marginTop: 8 }}>
          Solution : {ticket.solution}
        </div>
      )}
      {ticket.similarity !== undefined && (
        <div style={{ fontSize: 11, color: "#6b7280", marginTop: 6 }}>
          Similarite : {Math.round(ticket.similarity * 100)}%
        </div>
      )}
    </div>
  );
}
