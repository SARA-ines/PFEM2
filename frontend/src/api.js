const API =
  import.meta.env.VITE_API_URL ||
  `${window.location.protocol}//${window.location.hostname}:8000`;

const AUTH_STORAGE_KEY = "pfem2-auth-session";

export function getStoredAuthSession() {
  try {
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function setStoredAuthSession(session) {
  window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session));
}

export function clearStoredAuthSession() {
  window.localStorage.removeItem(AUTH_STORAGE_KEY);
}

async function request(path, options = {}) {
  try {
    const session = getStoredAuthSession();
    const headers = {
      ...(options.headers || {}),
    };
    if (session?.access_token) {
      headers.Authorization = `Bearer ${session.access_token}`;
    }

    const response = await fetch(`${API}${path}`, { ...options, headers });
    if (!response.ok) {
      let message = "Erreur de connexion au serveur";
      try {
        const data = await response.json();
        if (data?.detail) {
          message = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
        }
      } catch {
        // Ignore JSON parsing failure and keep default message.
      }
      if (response.status === 401) {
        clearStoredAuthSession();
        window.dispatchEvent(new CustomEvent("pfem2-session-expired"));
      }
      throw new Error(message);
    }
    return response.json();
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(`Backend non accessible sur ${API}`);
    }
    throw error;
  }
}

export function fetchClientTickets() {
  return request("/client/tickets");
}

export function registerClient(payload) {
  return request("/auth/client/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function registerTechnician(payload) {
  return request("/auth/technician/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function login(payload) {
  return request("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function forgotPassword(email) {
  return request("/auth/forgot-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
}

export function resetPassword(token, newPassword) {
  return request("/auth/reset-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, new_password: newPassword }),
  });
}

export function createClientTicket(payload) {
  return request("/client/tickets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function assignClientTicket(payload) {
  return request("/client/tickets/assign", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteClientTicket(ticketId) {
  return request(`/client/tickets/${ticketId}`, { method: "DELETE" });
}

export function fetchTechnicianTickets() {
  return request("/technician/tickets");
}

export function fetchReportsSummary() {
  return request("/reports/summary");
}

export function sendMessage(payload) {
  return request("/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function fetchConversationSession(sessionId) {
  return request(`/session/${sessionId}`);
}

export function fetchChatHistory() {
  return request("/client/chat-history");
}

export function fetchConversations() {
  return request("/client/conversations");
}

export function updateTicketPriority(payload) {
  return request("/technician/tickets/priority", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function technicianTakeover(payload) {
  return request("/technician/tickets/takeover", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function replyToTicket(ticketId, message) {
  return request(`/client/tickets/${ticketId}/reply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
}

export function fetchNotifications() {
  return request("/notifications");
}

export function markNotificationRead(notificationId) {
  return request(`/notifications/${notificationId}/read`, { method: "PATCH" });
}

export function markAllNotificationsRead() {
  return request("/notifications/read-all", { method: "POST" });
}

export function technicianSendMessage(ticketId, message) {
  return request(`/technician/tickets/${ticketId}/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
}
