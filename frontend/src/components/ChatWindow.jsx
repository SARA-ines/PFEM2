import MessageBubble from "./MessageBubble";
import TicketCard from "./TicketCard";
import "./ChatWindow.css";

export default function ChatWindow({ messages, loading, bottomRef, similarTickets = [] }) {
  return (
    <div className="chat-messages-area">
      {messages.length === 0 && !loading && (
        <div className="chat-empty-state">
          <div className="chat-empty-icon">💬</div>
          <p>Démarrez la conversation en envoyant votre message ci-dessous.</p>
        </div>
      )}

      {messages.map((msg, index) => (
        <MessageBubble key={index} msg={msg} />
      ))}

      {similarTickets.length > 0 && (
        <div className="chat-similar-tickets">
          <div className="chat-similar-label">Cas similaires trouvés</div>
          {similarTickets.map((ticket) => (
            <TicketCard key={`${ticket.id}-${ticket.similarity}`} ticket={ticket} />
          ))}
        </div>
      )}

      {loading && (
        <div className="chat-typing-indicator">
          <div className="chat-bot-avatar">B</div>
          <div className="chat-typing-dots">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="chat-typing-dot"
                style={{ animationDelay: `${i * 0.2}s` }}
              />
            ))}
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
