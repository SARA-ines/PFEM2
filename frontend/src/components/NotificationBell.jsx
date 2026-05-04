import { useState, useEffect, useRef } from "react";
import { markNotificationRead, markAllNotificationsRead } from "../api";
import "./NotificationBell.css";

function formatRelativeTime(timestamp) {
  if (!timestamp) return "";
  const date = new Date(timestamp);
  const diffMs = Date.now() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return "À l'instant";
  if (diffMins < 60) return `Il y a ${diffMins} min`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `Il y a ${diffHours}h`;
  return date.toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
}

export default function NotificationBell({ notifications, onNotificationClick, onMarkAllRead, onNotificationRead }) {
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef(null);

  const unreadCount = notifications.filter((n) => !n.isRead).length;

  useEffect(() => {
    function handleClickOutside(e) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  function handleNotificationClick(notif) {
    if (!notif.isRead) {
      markNotificationRead(notif.id).catch(() => {});
      onNotificationRead(notif.id);
    }
    setOpen(false);
    onNotificationClick(notif.ticketId);
  }

  function handleMarkAllRead() {
    markAllNotificationsRead().catch(() => {});
    onMarkAllRead();
    setOpen(false);
  }

  return (
    <div className="notif-bell-wrapper" ref={wrapperRef}>
      <button
        type="button"
        className={`notif-bell-btn${open ? " open" : ""}`}
        onClick={() => setOpen((prev) => !prev)}
        aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} non lues)` : ""}`}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {unreadCount > 0 && (
          <span className="notif-badge" aria-label={`${unreadCount} notifications non lues`}>
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="notif-dropdown" role="dialog" aria-label="Panneau de notifications">
          <div className="notif-dropdown-header">
            <strong>Notifications</strong>
            {unreadCount > 0 && (
              <button type="button" className="notif-mark-all-btn" onClick={handleMarkAllRead}>
                Tout marquer lu
              </button>
            )}
          </div>

          <div className="notif-list">
            {notifications.length === 0 ? (
              <div className="notif-empty">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#c0cde0" strokeWidth="1.5">
                  <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                  <path d="M13.73 21a2 2 0 0 1-3.46 0" />
                </svg>
                <p>Aucune notification pour le moment</p>
              </div>
            ) : (
              notifications.map((notif) => (
                <button
                  key={notif.id}
                  type="button"
                  className={`notif-item${!notif.isRead ? " unread" : ""}`}
                  onClick={() => handleNotificationClick(notif)}
                >
                  {!notif.isRead && <span className="notif-unread-dot" aria-hidden="true" />}
                  <div className="notif-item-avatar">
                    {(notif.senderName || "T").charAt(0).toUpperCase()}
                  </div>
                  <div className="notif-item-body">
                    <div className="notif-item-top">
                      <span className="notif-sender">{notif.senderName || "Technicien"}</span>
                      <time className="notif-time">{formatRelativeTime(notif.createdAt)}</time>
                    </div>
                    <p className="notif-ticket-ref">
                      Ticket #{notif.ticketId}
                      {notif.ticketTitle ? ` — ${notif.ticketTitle}` : ""}
                    </p>
                    <p className="notif-preview">{notif.messagePreview}</p>
                  </div>
                </button>
              ))
            )}
          </div>

          {notifications.length > 0 && (
            <div className="notif-dropdown-footer">
              <span>{notifications.length} notification{notifications.length > 1 ? "s" : ""}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
