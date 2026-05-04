export default function MessageBubble({ msg }) {
  const isUser = msg.role === "user";

  return (
    <div className={`chat-message-row ${isUser ? "user" : "assistant"}`}>
      {!isUser && (
        <div className="chat-bot-avatar">B</div>
      )}

      <div className={`chat-bubble ${isUser ? "user" : "assistant"}`}>
        {msg.content}
      </div>

      {isUser && (
        <div className="chat-user-avatar">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 12c2.7 0 5-2.3 5-5s-2.3-5-5-5-5 2.3-5 5 2.3 5 5 5zm0 2c-3.3 0-10 1.7-10 5v1h20v-1c0-3.3-6.7-5-10-5z"/>
          </svg>
        </div>
      )}
    </div>
  );
}
