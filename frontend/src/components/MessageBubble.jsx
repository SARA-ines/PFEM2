export default function MessageBubble({ msg }) {
  const isUser = msg.role === "user";

  return (
    <div
      style={{
        display: "flex",
        justifyContent: isUser ? "flex-end" : "flex-start",
        marginBottom: 16,
        alignItems: "flex-end",
        gap: 10,
      }}
    >
      {!isUser && (
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
      )}

      <div
        style={{
          maxWidth: "84%",
          padding: "14px 18px",
          borderRadius: isUser ? "20px 20px 6px 20px" : "6px 20px 20px 20px",
          background: isUser ? "#2563eb" : "#ffffff",
          color: isUser ? "#ffffff" : "#111827",
          fontSize: 16,
          lineHeight: 1.7,
          boxShadow: "0 6px 18px rgba(15, 35, 65, 0.08)",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {msg.content}
      </div>
    </div>
  );
}
