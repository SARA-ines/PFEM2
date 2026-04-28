import MessageBubble from "./MessageBubble";
import TicketCard from "./TicketCard";

export default function ChatWindow({ messages, loading, bottomRef, similarTickets }) {
  const usefulTickets = (similarTickets || []).filter((ticket) => (ticket.similarity || 0) >= 0.25);

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "20px 16px", background: "#f8fafc" }}>
      {messages.map((msg, index) => (
        <MessageBubble key={index} msg={msg} />
      ))}

      {usefulTickets.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: "#475569", marginBottom: 6 }}>
            Tickets similaires
          </div>
          {usefulTickets.map((ticket) => (
            <TicketCard key={`${ticket.id}-${ticket.similarity}`} ticket={ticket} />
          ))}
        </div>
      )}

      {loading && (
        <div style={{ display: "flex", gap: 4, padding: "10px 14px" }}>
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: "#6b7280",
                animation: `bounce 1s ${i * 0.15}s infinite`,
              }}
            />
          ))}
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
