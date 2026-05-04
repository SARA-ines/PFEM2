import MessageBubble from "./MessageBubble";
import TicketCard from "./TicketCard";

export default function ChatWindow({ messages, loading, bottomRef, similarTickets = [] }) {
  return (
    <div
      style={{
        flex: 1,
        minHeight: 0,
        overflowY: "auto",
        padding: "28px 24px",
        background: "#f0f4f8",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {messages.map((msg, index) => (
        <MessageBubble key={index} msg={msg} />
      ))}

      {similarTickets.length > 0 && (
        <div
          style={{
            margin: "4px 0 18px 48px",
            maxWidth: 560,
            background: "#e8f0fb",
            border: "1px solid #c9d8ee",
            borderRadius: 8,
            padding: 12,
          }}
        >
          <div style={{ fontSize: 12, fontWeight: 800, color: "#17355a", marginBottom: 6 }}>
            Cas similaires trouves
          </div>
          {similarTickets.map((ticket) => (
            <TicketCard key={`${ticket.id}-${ticket.similarity}`} ticket={ticket} />
          ))}
        </div>
      )}

      {loading && (
        <div style={{ display: "flex", alignItems: "flex-end", gap: 8, marginBottom: 12 }}>
          <div
            style={{
              width: 38,
              height: 38,
              borderRadius: "50%",
              background: "linear-gradient(135deg, #2563eb, #7c3aed)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
              fontSize: 15,
              color: "#fff",
              fontWeight: 700,
            }}
          >
            B
          </div>
          <div
            style={{
              padding: "12px 16px",
              background: "#ffffff",
              borderRadius: "4px 18px 18px 18px",
              boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
              display: "flex",
              gap: 5,
              alignItems: "center",
            }}
          >
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: "#9ca3af",
                  animation: `bounce 1.2s ${i * 0.2}s infinite ease-in-out`,
                }}
              />
            ))}
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
