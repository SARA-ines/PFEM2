import { useDeferredValue, useEffect, useRef, useState } from "react";

import {
  clearStoredAuthSession,
  createClientTicket,
  assignClientTicket,
  deleteClientTicket,
  fetchConversationSession,
  fetchChatHistory,
  fetchClientTickets,
  fetchConversations,
  fetchNotifications,
  fetchReportsSummary,
  getStoredAuthSession,
  forgotPassword,
  resetPassword,
  login,
  registerClient,
  registerTechnician,
  sendMessage,
  setStoredAuthSession,
  fetchTechnicianTickets,
  updateTicketPriority,
  technicianTakeover,
  technicianSendMessage,
  replyToTicket,
} from "./api";
import ChatWindow from "./components/ChatWindow";
import FonctionnalitesPicker from "./components/FonctionnalitesPicker";
import NotificationBell from "./components/NotificationBell";
import "./App.css";
import "./improvements.css";

const clientTabs = [
  { key: "tous", label: "Tous" },
  { key: "en_attente", label: "En attente" },
  { key: "attribue", label: "Assignes" },
  { key: "resolu", label: "Resolus" },
];

const techTabs = [
  { key: "tous", label: "Toute la file" },
  { key: "nouveau", label: "Nouveaux" },
  { key: "en_cours", label: "En cours" },
  { key: "en_attente_client", label: "En attente client" },
  { key: "resolu", label: "Resolus" },
];

const defaultClientUser = {
  name: "Marc Dupont",
  initials: "M",
  role: "Responsable support client",
  clientId: "client-big-logistics",
  clientName: "BIG Logistique Algerie",
  email: "marc.dupont@big.fr",
  phone: "0612345678",
};

const defaultTechnicianUser = {
  name: "Zakaria Benali",
  role: "Technicien Support ERP",
  shift: "08:00 - 17:00",
  initials: "ZB",
};

const emptyReports = {
  kpis: {
    resolved: { value: 0, delta: "" },
    avg_resolution: { value: "0h", delta: "" },
    satisfaction: { value: "0%", delta: "" },
    waiting: { value: 0, delta: "" },
  },
  monthly_trends: [],
  categories: [],
};

const initialAssistantMessage = {
  role: "assistant",
  content:
    "Bonjour. Remplissez le formulaire et cliquez sur \"Qualifier avec l'assistant\" pour demarrer. Je connaitrai deja votre logiciel, module et version - vous n'aurez pas a les resaisir.",
};

const MIN_USEFUL_SIMILARITY = 0.25;

function clientChatStorageKey(clientId) {
  return `pfem2-client-chat:${clientId || "anonymous"}`;
}

function readStoredClientChat(clientId) {
  try {
    const raw = window.localStorage.getItem(clientChatStorageKey(clientId));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    if ("current" in parsed || "history" in parsed) {
      return parsed;
    }
    return { current: parsed, history: [] };
  } catch {
    return null;
  }
}

function writeStoredClientChat(clientId, snapshot) {
  try {
    window.localStorage.setItem(clientChatStorageKey(clientId), JSON.stringify(snapshot));
  } catch {
    // Ignore localStorage failures and keep chat usable in-memory.
  }
}

function clearStoredClientChat(clientId) {
  try {
    window.localStorage.removeItem(clientChatStorageKey(clientId));
  } catch {
    // Ignore localStorage failures.
  }
}

function buildConversationTitle(form, messages) {
  const explicitTitle = (form?.title || "").trim();
  if (explicitTitle) return explicitTitle;
  const firstUserMessage = (messages || []).find((item) => item.role === "user" && item.content?.trim());
  if (firstUserMessage) {
    return firstUserMessage.content.trim().slice(0, 72);
  }
  return "Nouvelle conversation";
}

function buildDraftFromForm(form) {
  return [form?.title || "", form?.description || ""].filter(Boolean).join("\n").trim();
}

function countWords(text) {
  return (text || "").trim().split(/\s+/).filter(Boolean).length;
}

function validateTicketForm(form) {
  const errors = {};

  if (!form.title.trim()) {
    errors.title = "Le titre est obligatoire.";
  }
  if (!form.module.trim()) {
    errors.module = "Le module est obligatoire.";
  }
  if (!form.softwareName.trim()) {
    errors.softwareName = "Le nom du logiciel est obligatoire.";
  }
  if (!form.softwareVersion.trim()) {
    errors.softwareVersion = "La version du logiciel est obligatoire.";
  }
  if (!form.description.trim()) {
    errors.description = "La description est obligatoire.";
  } else if (countWords(form.description) < 5) {
    errors.description = "La description doit contenir au moins 5 mots.";
  }
  if (form.phone.length !== 10) {
    errors.phone = "Le telephone doit contenir exactement 10 chiffres.";
  }

  return {
    errors,
    isValid: Object.keys(errors).length === 0,
  };
}

function buildAssistantPromptFromForm(form) {
  const parts = [
    form?.title?.trim() ? `Titre: ${form.title.trim()}` : "",
    form?.module?.trim() ? `Module: ${form.module.trim()}` : "",
    form?.softwareName?.trim() ? `Logiciel: ${form.softwareName.trim()}` : "",
    form?.softwareVersion?.trim() ? `Version: ${form.softwareVersion.trim()}` : "",
    form?.fonctionnalites?.trim() ? `Fonctionnalites utilisees: ${form.fonctionnalites.trim()}` : "",
    form?.description?.trim() ? `Description: ${form.description.trim()}` : "",
  ].filter(Boolean);

  return parts.join("\n").trim();
}

function applyFormHintsToAssistantState(state, form) {
  const nextState = { ...(state || {}) };
  const selectedModule = (form?.module || "").trim();
  const softwareName = (form?.softwareName || "").trim();
  const softwareVersion = (form?.softwareVersion || "").trim();

  if (selectedModule) {
    nextState.module = selectedModule;
  }

  if (softwareName) {
    nextState.software = softwareName;
  }

  if (softwareVersion) {
    nextState.software_version = softwareVersion;
  }

  return nextState;
}

function buildConversationPreview(messages) {
  const lastAssistant = [...(messages || [])].reverse().find((item) => item.role === "assistant" && item.content?.trim());
  const source = lastAssistant?.content || messages?.[messages.length - 1]?.content || "";
  return source.trim().slice(0, 120);
}

function buildConversationSnapshot({ chatSessionId, chatMessages, similarTickets, lastAssistantState, form, currentTicketId }) {
  const messages = Array.isArray(chatMessages) ? chatMessages : [];
  return {
    id: chatSessionId || `local-${Date.now()}`,
    chatSessionId: chatSessionId || "",
    title: buildConversationTitle(form, messages),
    preview: buildConversationPreview(messages),
    updatedAt: new Date().toISOString(),
    chatMessages: messages,
    similarTickets: Array.isArray(similarTickets) ? similarTickets : [],
    lastAssistantState: lastAssistantState || {},
    form: form || {},
    currentTicketId: currentTicketId || null,
  };
}

function isMeaningfulConversation(snapshot) {
  if (!snapshot) return false;
  if (snapshot.chatSessionId) return true;
  if ((snapshot.form?.title || "").trim() || (snapshot.form?.description || "").trim()) return true;
  const nonSeedMessages = (snapshot.chatMessages || []).filter(
    (item) => item.content?.trim() && item.content !== initialAssistantMessage.content
  );
  return nonSeedMessages.length > 0;
}

function hydrateConversation(snapshot, setters) {
  if (!snapshot) return;
  setters.setChatSessionId(snapshot.chatSessionId || "");
  setters.setChatMessages(
    Array.isArray(snapshot.chatMessages) && snapshot.chatMessages.length
      ? snapshot.chatMessages
      : [initialAssistantMessage]
  );
  setters.setSimilarTickets(Array.isArray(snapshot.similarTickets) ? snapshot.similarTickets : []);
  setters.setLastAssistantState(snapshot.lastAssistantState || {});
  setters.setCurrentTicketId?.(snapshot.currentTicketId || null);
  setters.setForm((prev) => ({
    ...prev,
    ...((snapshot.form && typeof snapshot.form === "object") ? snapshot.form : {}),
    phone: ((snapshot.form && snapshot.form.phone) || prev.phone || "").slice(0, 10),
  }));
}

function formatConversationDate(value) {
  try {
    return new Date(value).toLocaleString("fr-FR", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

function groupMessagesIntoConversations(msgs) {
  if (!msgs.length) return [];
  const GAP_MS = 30 * 60 * 1000;
  const groups = [];
  let current = [msgs[0]];
  for (let i = 1; i < msgs.length; i++) {
    const prevT = current[current.length - 1].timestamp ? new Date(current[current.length - 1].timestamp).getTime() : 0;
    const currT = msgs[i].timestamp ? new Date(msgs[i].timestamp).getTime() : 0;
    if (prevT && currT && currT - prevT > GAP_MS) {
      groups.push(current);
      current = [msgs[i]];
    } else {
      current.push(msgs[i]);
    }
  }
  groups.push(current);
  return groups;
}

function findNearestTicket(group, tickets) {
  if (!tickets || !tickets.length) return null;
  const firstT = group[0]?.timestamp ? new Date(group[0].timestamp).getTime() : 0;
  const lastT = group[group.length - 1]?.timestamp ? new Date(group[group.length - 1].timestamp).getTime() : 0;
  if (!firstT) return null;
  let best = null;
  let bestDiff = Infinity;
  for (const t of tickets) {
    if (!t.timestamp) continue;
    const tTime = new Date(t.timestamp).getTime();
    if (tTime >= firstT - 5 * 60 * 1000 && tTime <= lastT + 60 * 60 * 1000) {
      const diff = Math.abs(tTime - firstT);
      if (diff < bestDiff) { bestDiff = diff; best = t; }
    }
  }
  return best;
}

export default function App() {
  const storedSession = getStoredAuthSession();
  const [authSession, setAuthSession] = useState(storedSession);
  const [loginPrefill, setLoginPrefill] = useState({ role: "client", email: "" });
  const [clientUser, setClientUser] = useState(defaultClientUser);
  const [technicianUser, setTechnicianUser] = useState(defaultTechnicianUser);

  // Détecte ?reset_token=... dans l'URL au chargement
  const urlResetToken = new URLSearchParams(window.location.search).get("reset_token") || "";
  const [view, setView] = useState(urlResetToken ? "reset-password" : "login");

  function handleClientRegistrationSuccess(user) {
    setClientUser({
      name: user.full_name,
      initials: buildInitials(user.full_name),
      role: "Client",
      clientId: user.client_id,
      clientName: user.company,
      email: user.email,
      phone: user.phone,
    });
    setLoginPrefill({ role: "client", email: user.email || "" });
    setView("login");
  }

  function handleTechnicianRegistrationSuccess(user) {
    setTechnicianUser({
      name: user.full_name,
      initials: buildInitials(user.full_name),
      role: "Technicien Support ERP",
      shift: "08:00 - 17:00",
    });
    setLoginPrefill({ role: "technicien", email: user.email || "" });
    setView("login");
  }

  function handleLoginSuccess(user) {
    const session = { access_token: user.access_token, user };
    setStoredAuthSession(session);
    setAuthSession(session);
    if (user.role === "client") {
      setClientUser({
        name: user.full_name,
        initials: buildInitials(user.full_name),
        role: "Client",
        clientId: user.client_id,
        clientName: user.company,
        email: user.email,
        phone: user.phone,
      });
      setView("client");
      return;
    }

    setTechnicianUser({
      name: user.full_name,
      initials: buildInitials(user.full_name),
      role: "Technicien Support ERP",
      shift: "08:00 - 17:00",
    });
    setView("technicien");
  }

  function handleLogout() {
    clearStoredAuthSession();
    setAuthSession(null);
    setClientUser(defaultClientUser);
    setTechnicianUser(defaultTechnicianUser);
    setView("login");
  }

  useEffect(() => {
    const handler = () => handleLogout();
    window.addEventListener("pfem2-session-expired", handler);
    return () => window.removeEventListener("pfem2-session-expired", handler);
  }, []);

  function openProtectedView(target) {
    const role = authSession?.user?.role;
    if (target === "client" && role === "client") {
      setView("client");
      return;
    }
    if (target === "technicien" && role === "technicien") {
      setView("technicien");
      return;
    }
    setView("login");
  }

  return (
    <div className="app-shell">
      {view === "login" ? (
        <LoginView
          onSuccess={handleLoginSuccess}
          onOpenClientRegistration={() => setView("registration")}
          onOpenTechnicianRegistration={() => setView("registration-technician")}
          onForgotPassword={() => setView("forgot-password")}
          initialRole={loginPrefill.role}
          initialEmail={loginPrefill.email}
        />
      ) : view === "registration" ? (
        <RegistrationClientView onSuccess={handleClientRegistrationSuccess} onOpenLogin={() => setView("login")} />
      ) : view === "registration-technician" ? (
        <RegistrationTechnicianView onSuccess={handleTechnicianRegistrationSuccess} onOpenLogin={() => setView("login")} />
      ) : view === "forgot-password" ? (
        <ForgotPasswordView onOpenLogin={() => setView("login")} />
      ) : view === "reset-password" ? (
        <ResetPasswordView token={urlResetToken} onOpenLogin={() => setView("login")} />
      ) : view === "client" ? (
        <ClientView currentUser={clientUser} onLogout={handleLogout} />
      ) : (
        <TechnicianView technician={technicianUser} onLogout={handleLogout} />
      )}
    </div>
  );
}

function LoginView({ onSuccess, onOpenClientRegistration, onOpenTechnicianRegistration, onForgotPassword, initialRole = "client", initialEmail = "" }) {
  const [form, setForm] = useState({
    role: initialRole,
    email: initialEmail,
    password: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    setForm((prev) => ({
      ...prev,
      role: initialRole || "client",
      email: initialEmail || "",
      password: "",
    }));
    setMessage("");
  }, [initialRole, initialEmail]);

  function setField(name, value) {
    setForm((prev) => ({ ...prev, [name]: value }));
  }

  const registrationLabel =
    form.role === "technicien" ? "S'inscrire en tant que Technicien" : "S'inscrire en tant que Client";

  function openRegistration() {
    if (form.role === "technicien") {
      onOpenTechnicianRegistration?.();
      return;
    }
    onOpenClientRegistration?.();
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (!form.email.trim() || !form.password) {
      setMessage("Email et mot de passe obligatoires.");
      return;
    }

    setSubmitting(true);
    setMessage("");

    try {
      const response = await login({
        role: form.role,
        email: form.email,
        password: form.password,
      });
      onSuccess?.({ ...response.user, access_token: response.access_token });
    } catch (error) {
      setMessage(error.message || "Erreur lors de la connexion.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-shell">
      <section className="registration-hero">
        <p className="registration-kicker">Authentification</p>
        <h1>Connexion</h1>
        <p>Accedez a votre espace support selon votre role.</p>
      </section>

      <form className="login-card" onSubmit={handleSubmit}>
        <div className="login-role-block">
          <h2>Selectionnez votre role</h2>
          <div className="login-role-grid">
            <button
              type="button"
              className={`role-card${form.role === "client" ? " active" : ""}`}
              onClick={() => setField("role", "client")}
            >
              <UserOutline />
              <span>Client</span>
            </button>
            <button
              type="button"
              className={`role-card${form.role === "technicien" ? " active" : ""}`}
              onClick={() => setField("role", "technicien")}
            >
              <WrenchIcon />
              <span>Technicien</span>
            </button>
          </div>
        </div>

        <label className="registration-field">
          <span>Adresse email</span>
          <div className="registration-input">
            <MailSmall />
            <input
              type="email"
              value={form.email}
              onChange={(e) => setField("email", e.target.value)}
              placeholder="Entrez votre email"
            />
          </div>
        </label>

        <label className="registration-field">
          <span>Mot de passe</span>
          <div className="registration-input">
            <LockOutline />
            <input
              type="password"
              value={form.password}
              onChange={(e) => setField("password", e.target.value)}
              placeholder="Entrez votre mot de passe"
            />
          </div>
        </label>

        <div className="login-links-row">
          <button type="button" className="text-link forgot-link" onClick={onForgotPassword}>Mot de passe oublie ?</button>
        </div>

        {message ? <p className="registration-message error">{message}</p> : null}

        <button type="submit" className="registration-submit">
          {submitting ? "Connexion..." : "Se connecter"}
          <ArrowRightIcon />
        </button>

        <div className="login-footer">
          <p>Vous n&apos;avez pas de compte ?</p>
          <button type="button" className="text-link login-register-link" onClick={openRegistration}>
            {registrationLabel}
          </button>
        </div>
      </form>
    </div>
  );
}

function ForgotPasswordView({ onOpenLogin }) {
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState("idle"); // "idle" | "success" | "error"
  const [message, setMessage] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    if (!email.trim()) {
      setStatus("error");
      setMessage("Veuillez saisir votre adresse email.");
      return;
    }
    setSubmitting(true);
    setStatus("idle");
    setMessage("");
    try {
      await forgotPassword(email.trim());
      setStatus("success");
      setMessage("Si un compte est associé à cette adresse, vous recevrez un lien de réinitialisation sous peu.");
    } catch (err) {
      setStatus("error");
      setMessage(err.message || "Une erreur est survenue. Veuillez réessayer.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-shell">
      <section className="registration-hero">
        <p className="registration-kicker">Sécurité</p>
        <h1>Mot de passe oublié</h1>
        <p>Saisissez votre adresse email pour recevoir un lien de réinitialisation.</p>
      </section>

      <form className="login-card forgot-card" onSubmit={handleSubmit}>
        {status === "success" ? (
          <div className="forgot-success-state">
            <div className="forgot-success-icon">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#16a34a" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                <polyline points="22 4 12 14.01 9 11.01" />
              </svg>
            </div>
            <h3>Email envoyé !</h3>
            <p>{message}</p>
            <p className="forgot-check-spam">Vérifiez aussi votre dossier spam.</p>
            <button type="button" className="registration-submit" onClick={onOpenLogin} style={{ marginTop: 8 }}>
              Retour à la connexion
              <ArrowRightIcon />
            </button>
          </div>
        ) : (
          <>
            <div className="forgot-intro">
              <div className="forgot-icon-wrap">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#2563eb" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                  <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                </svg>
              </div>
              <p>Entrez l&apos;email associé à votre compte et nous vous enverrons les instructions de réinitialisation.</p>
            </div>

            <label className="registration-field">
              <span>Adresse email</span>
              <div className="registration-input">
                <MailSmall />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="votre@email.com"
                  autoFocus
                  disabled={submitting}
                />
              </div>
            </label>

            {status === "error" && message && (
              <p className="registration-message error">{message}</p>
            )}

            <button type="submit" className="registration-submit" disabled={submitting}>
              {submitting ? "Envoi en cours..." : "Envoyer le lien"}
              {!submitting && <ArrowRightIcon />}
            </button>

            <div className="login-footer">
              <p>Vous vous souvenez de votre mot de passe ?</p>
              <button type="button" className="text-link login-register-link" onClick={onOpenLogin}>
                Retour à la connexion
              </button>
            </div>
          </>
        )}
      </form>
    </div>
  );
}


function ResetPasswordView({ token, onOpenLogin }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState("idle"); // "idle" | "success" | "error"
  const [message, setMessage] = useState("");
  const [showPw, setShowPw] = useState(false);

  const checks = [
    { label: "Au moins 8 caractères", ok: password.length >= 8 },
    { label: "Majuscule et minuscule", ok: /[a-z]/.test(password) && /[A-Z]/.test(password) },
    { label: "Au moins un chiffre", ok: /\d/.test(password) },
    { label: "Au moins un caractère spécial", ok: /[^A-Za-z0-9]/.test(password) },
  ];
  const allChecksOk = checks.every((c) => c.ok);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!allChecksOk) { setStatus("error"); setMessage("Le mot de passe ne respecte pas les critères."); return; }
    if (password !== confirm) { setStatus("error"); setMessage("Les mots de passe ne correspondent pas."); return; }
    if (!token) { setStatus("error"); setMessage("Token manquant. Veuillez refaire une demande."); return; }

    setSubmitting(true);
    setStatus("idle");
    setMessage("");
    try {
      const res = await resetPassword(token, password);
      setStatus("success");
      setMessage(res.message || "Mot de passe réinitialisé avec succès.");
      // Nettoyer le token de l'URL sans rechargement
      window.history.replaceState({}, "", window.location.pathname);
    } catch (err) {
      setStatus("error");
      setMessage(err.message || "Une erreur est survenue.");
    } finally {
      setSubmitting(false);
    }
  }

  if (!token) {
    return (
      <div className="login-shell">
        <section className="registration-hero">
          <p className="registration-kicker">Erreur</p>
          <h1>Lien invalide</h1>
          <p>Ce lien de réinitialisation est manquant ou corrompu.</p>
        </section>
        <div className="login-card forgot-card" style={{ textAlign: "center" }}>
          <button type="button" className="registration-submit" onClick={onOpenLogin}>
            Retour à la connexion <ArrowRightIcon />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="login-shell">
      <section className="registration-hero">
        <p className="registration-kicker">Sécurité</p>
        <h1>Nouveau mot de passe</h1>
        <p>Choisissez un mot de passe fort pour sécuriser votre compte.</p>
      </section>

      <form className="login-card forgot-card" onSubmit={handleSubmit}>
        {status === "success" ? (
          <div className="forgot-success-state">
            <div className="forgot-success-icon">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#16a34a" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                <polyline points="22 4 12 14.01 9 11.01" />
              </svg>
            </div>
            <h3>Mot de passe mis à jour !</h3>
            <p>{message}</p>
            <button type="button" className="registration-submit" onClick={onOpenLogin} style={{ marginTop: 8 }}>
              Se connecter <ArrowRightIcon />
            </button>
          </div>
        ) : (
          <>
            <label className="registration-field">
              <span>Nouveau mot de passe</span>
              <div className="registration-input">
                <LockOutline />
                <input
                  type={showPw ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Créer un mot de passe"
                  autoFocus
                  disabled={submitting}
                />
                <button type="button" style={{ background: "none", border: "none", cursor: "pointer", padding: "0 4px", color: "#5d79a3" }} onClick={() => setShowPw((v) => !v)}>
                  {showPw ? "🙈" : "👁"}
                </button>
              </div>
            </label>

            {password.length > 0 && (
              <ul className="reset-checks">
                {checks.map((c) => (
                  <li key={c.label} className={c.ok ? "ok" : "nok"}>
                    <span>{c.ok ? "✓" : "✗"}</span> {c.label}
                  </li>
                ))}
              </ul>
            )}

            <label className="registration-field">
              <span>Confirmer le mot de passe</span>
              <div className="registration-input">
                <LockOutline />
                <input
                  type={showPw ? "text" : "password"}
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  placeholder="Répéter le mot de passe"
                  disabled={submitting}
                />
              </div>
            </label>

            {status === "error" && message && (
              <p className="registration-message error">{message}</p>
            )}

            <button type="submit" className="registration-submit" disabled={submitting || !allChecksOk || !confirm}>
              {submitting ? "Mise à jour..." : "Enregistrer le mot de passe"}
              {!submitting && <ArrowRightIcon />}
            </button>

            <div className="login-footer">
              <button type="button" className="text-link login-register-link" onClick={onOpenLogin}>
                Annuler — retour à la connexion
              </button>
            </div>
          </>
        )}
      </form>
    </div>
  );
}


function RegistrationClientView({ onSuccess, onOpenLogin }) {
  const [form, setForm] = useState({
    fullName: "",
    email: "",
    phone: "",
    company: "",
    password: "",
    confirmPassword: "",
    acceptedTerms: false,
  });
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");
  const [messageTone, setMessageTone] = useState("info");

  function setField(name, value) {
    setForm((prev) => ({ ...prev, [name]: value }));
  }

  function passwordChecks() {
    return [
      { label: "Au moins 8 caracteres", ok: form.password.length >= 8 },
      { label: "Lettres majuscules et minuscules", ok: /[a-z]/.test(form.password) && /[A-Z]/.test(form.password) },
      { label: "Au moins un chiffre", ok: /\d/.test(form.password) },
      { label: "Au moins un caractere special", ok: /[^A-Za-z0-9]/.test(form.password) },
    ];
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (!form.fullName.trim() || !form.email.trim() || !form.phone.trim() || !form.company.trim() || !form.password || !form.confirmPassword) {
      setMessageTone("error");
      setMessage("Tous les champs sont obligatoires.");
      return;
    }
    if (form.password !== form.confirmPassword) {
      setMessageTone("error");
      setMessage("Les mots de passe ne correspondent pas.");
      return;
    }
    if (!form.acceptedTerms) {
      setMessageTone("error");
      setMessage("Vous devez accepter les conditions generales.");
      return;
    }

    setSubmitting(true);
    setMessage("");

    try {
      const response = await registerClient({
        full_name: form.fullName,
        email: form.email,
        phone: form.phone,
        company: form.company,
        password: form.password,
      });
      setMessageTone("success");
      setMessage("Compte client cree. Redirection vers l'interface client.");
      onSuccess?.(response.user);
    } catch (error) {
      setMessageTone("error");
      setMessage(error.message || "Erreur lors de l'inscription client.");
    } finally {
      setSubmitting(false);
    }
  }

  const checks = passwordChecks();

  return (
    <div className="registration-shell">
      <section className="registration-hero">
        <p className="registration-kicker">Espace client</p>
        <h1>Inscription Client</h1>
        <p>Creez votre compte pour soumettre des tickets et acceder au suivi support.</p>
      </section>

      <form className="registration-card" onSubmit={handleSubmit}>
        <div className="registration-grid single">
          <label className="registration-field">
            <span>Nom complet</span>
            <div className="registration-input">
              <UserOutline />
              <input
                value={form.fullName}
                onChange={(e) => setField("fullName", e.target.value)}
                placeholder="Entrez votre nom complet"
              />
            </div>
          </label>
        </div>

        <div className="registration-grid">
          <label className="registration-field">
            <span>Adresse email</span>
            <div className="registration-input">
              <MailSmall />
              <input
                type="email"
                value={form.email}
                onChange={(e) => setField("email", e.target.value)}
                placeholder="email@exemple.fr"
              />
            </div>
          </label>
          <label className="registration-field">
            <span>Telephone</span>
            <div className="registration-input">
              <PhoneOutline />
              <input
                value={form.phone}
                onChange={(e) => setField("phone", e.target.value.replace(/[^\d+ ]/g, "").slice(0, 20))}
                placeholder="+33 6 12 34 56 78"
              />
            </div>
          </label>
        </div>

        <div className="registration-grid single">
          <label className="registration-field">
            <span>Entreprise</span>
            <div className="registration-input">
              <BuildingOutline />
              <input
                value={form.company}
                onChange={(e) => setField("company", e.target.value)}
                placeholder="Nom de votre entreprise"
              />
            </div>
          </label>
        </div>

        <div className="registration-grid">
          <label className="registration-field">
            <span>Mot de passe</span>
            <div className="registration-input">
              <LockOutline />
              <input
                type="password"
                value={form.password}
                onChange={(e) => setField("password", e.target.value)}
                placeholder="Creer un mot de passe"
              />
            </div>
          </label>
          <label className="registration-field">
            <span>Confirmer le mot de passe</span>
            <div className="registration-input">
              <LockOutline />
              <input
                type="password"
                value={form.confirmPassword}
                onChange={(e) => setField("confirmPassword", e.target.value)}
                placeholder="Confirmer le mot de passe"
              />
            </div>
          </label>
        </div>

        <div className="password-requirements">
          <strong>Exigences du mot de passe :</strong>
          <ul className="bullet-list password-list">
            {checks.map((check) => (
              <li key={check.label} className={check.ok ? "ok" : ""}>{check.label}</li>
            ))}
          </ul>
        </div>

        <label className="terms-row">
          <input
            type="checkbox"
            checked={form.acceptedTerms}
            onChange={(e) => setField("acceptedTerms", e.target.checked)}
          />
          <span>
            J&apos;accepte les <a href="#conditions">Conditions generales d&apos;utilisation</a> et la{" "}
            <a href="#confidentialite">Politique de confidentialite</a>
          </span>
        </label>

        {message ? <p className={`registration-message ${messageTone}`}>{message}</p> : null}

        <button type="submit" className="registration-submit">
          {submitting ? "Creation..." : "Creer mon compte client"}
          <ArrowRightIcon />
        </button>

        <div className="login-footer">
          <p>Vous avez deja un compte ?</p>
          <button type="button" className="text-link login-register-link" onClick={onOpenLogin}>
            Retour a la connexion
          </button>
        </div>
      </form>
    </div>
  );
}

function RegistrationTechnicianView({ onSuccess, onOpenLogin }) {
  const [form, setForm] = useState({
    fullName: "",
    email: "",
    phone: "",
    technicianId: "",
    specialty: "",
    password: "",
    confirmPassword: "",
    acceptedTerms: false,
  });
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");
  const [messageTone, setMessageTone] = useState("info");

  function setField(name, value) {
    setForm((prev) => ({ ...prev, [name]: value }));
  }

  function passwordChecks() {
    return [
      { label: "Au moins 8 caracteres", ok: form.password.length >= 8 },
      { label: "Lettres majuscules et minuscules", ok: /[a-z]/.test(form.password) && /[A-Z]/.test(form.password) },
      { label: "Au moins un chiffre", ok: /\d/.test(form.password) },
      { label: "Au moins un caractere special", ok: /[^A-Za-z0-9]/.test(form.password) },
    ];
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (!form.fullName.trim() || !form.email.trim() || !form.phone.trim() || !form.technicianId.trim() || !form.specialty.trim() || !form.password || !form.confirmPassword) {
      setMessageTone("error");
      setMessage("Tous les champs sont obligatoires.");
      return;
    }
    if (form.password !== form.confirmPassword) {
      setMessageTone("error");
      setMessage("Les mots de passe ne correspondent pas.");
      return;
    }
    if (!form.acceptedTerms) {
      setMessageTone("error");
      setMessage("Vous devez accepter les conditions generales.");
      return;
    }

    setSubmitting(true);
    setMessage("");

    try {
      const response = await registerTechnician({
        full_name: form.fullName,
        email: form.email,
        phone: form.phone,
        technician_id: form.technicianId,
        specialty: form.specialty,
        password: form.password,
      });
      setMessageTone("success");
      setMessage("Compte technicien cree. Vous pouvez maintenant vous connecter.");
      onSuccess?.(response.user);
    } catch (error) {
      setMessageTone("error");
      setMessage(error.message || "Erreur lors de l'inscription technicien.");
    } finally {
      setSubmitting(false);
    }
  }

  const checks = passwordChecks();

  return (
    <div className="registration-shell technician-registration-shell">
      <section className="registration-hero">
        <p className="registration-kicker">Espace technicien</p>
        <h1>Inscription Technicien</h1>
        <p>Creez votre compte technicien pour traiter les tickets et acceder a la console support.</p>
      </section>

      <form className="registration-card technician-card" onSubmit={handleSubmit}>
        <div className="registration-grid single">
          <label className="registration-field">
            <span>Nom complet</span>
            <div className="registration-input">
              <UserOutline />
              <input
                value={form.fullName}
                onChange={(e) => setField("fullName", e.target.value)}
                placeholder="Entrez votre nom complet"
              />
            </div>
          </label>
        </div>

        <div className="registration-grid">
          <label className="registration-field">
            <span>Adresse email</span>
            <div className="registration-input">
              <MailSmall />
              <input
                type="email"
                value={form.email}
                onChange={(e) => setField("email", e.target.value)}
                placeholder="email@exemple.fr"
              />
            </div>
          </label>
          <label className="registration-field">
            <span>Telephone</span>
            <div className="registration-input">
              <PhoneOutline />
              <input
                value={form.phone}
                onChange={(e) => setField("phone", e.target.value.replace(/[^\d+ ]/g, "").slice(0, 20))}
                placeholder="+33 6 12 34 56 78"
              />
            </div>
          </label>
        </div>

        <div className="registration-grid">
          <label className="registration-field">
            <span>ID Technicien</span>
            <div className="registration-input">
              <BadgeOutline />
              <input
                value={form.technicianId}
                onChange={(e) => setField("technicianId", e.target.value.toUpperCase())}
                placeholder="TECH-001"
              />
            </div>
          </label>
          <label className="registration-field">
            <span>Specialite</span>
            <div className="registration-input">
              <WrenchIcon />
              <select value={form.specialty} onChange={(e) => setField("specialty", e.target.value)}>
                <option value="">Selectionnez une specialite</option>
                <option value="Support ERP">Support ERP</option>
                <option value="Infrastructure">Infrastructure</option>
                <option value="Base de donnees">Base de donnees</option>
                <option value="Comptabilite / Finance">Comptabilite / Finance</option>
                <option value="Paie / RH">Paie / RH</option>
              </select>
            </div>
          </label>
        </div>

        <div className="registration-grid">
          <label className="registration-field">
            <span>Mot de passe</span>
            <div className="registration-input">
              <LockOutline />
              <input
                type="password"
                value={form.password}
                onChange={(e) => setField("password", e.target.value)}
                placeholder="Creer un mot de passe"
              />
            </div>
          </label>
          <label className="registration-field">
            <span>Confirmer le mot de passe</span>
            <div className="registration-input">
              <LockOutline />
              <input
                type="password"
                value={form.confirmPassword}
                onChange={(e) => setField("confirmPassword", e.target.value)}
                placeholder="Confirmer le mot de passe"
              />
            </div>
          </label>
        </div>

        <div className="password-requirements technician">
          <strong>Exigences du mot de passe :</strong>
          <ul className="bullet-list password-list">
            {checks.map((check) => (
              <li key={check.label} className={check.ok ? "ok" : ""}>{check.label}</li>
            ))}
          </ul>
        </div>

        <label className="terms-row">
          <input
            type="checkbox"
            checked={form.acceptedTerms}
            onChange={(e) => setField("acceptedTerms", e.target.checked)}
          />
          <span>
            J&apos;accepte les <a href="#conditions">Conditions generales d&apos;utilisation</a> et la{" "}
            <a href="#confidentialite">Politique de confidentialite</a>
          </span>
        </label>

        {message ? <p className={`registration-message ${messageTone}`}>{message}</p> : null}

        <button type="submit" className="registration-submit technician-submit">
          {submitting ? "Creation..." : "Creer mon compte technicien"}
          <ArrowRightIcon />
        </button>

        <div className="login-footer">
          <p>Vous avez deja un compte ?</p>
          <button type="button" className="text-link login-register-link" onClick={onOpenLogin}>
            Retour a la connexion
          </button>
        </div>
      </form>
    </div>
  );
}

const tdLabel = { padding: "5px 8px 5px 0", color: "#5a769b", fontWeight: 700, whiteSpace: "nowrap", verticalAlign: "top", width: "42%", fontSize: 12 };
const tdValue = { padding: "5px 0", color: "#17355a", verticalAlign: "top", fontWeight: 600 };

function ClientView({ currentUser = defaultClientUser, onLogout }) {
  const storageKey = clientChatStorageKey(currentUser.clientId);
  const [page, setPage] = useState("tickets");
  const [tab, setTab] = useState("tous");
  const deferredTab = useDeferredValue(tab);
  const [tickets, setTickets] = useState([]);
  const [stats, setStats] = useState({ total: 0, enAttente: 0, resolus: 0, ouverts: 0, attribues: 0 });
  const [selectedClientTicketId, setSelectedClientTicketId] = useState(null);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [chatSessionId, setChatSessionId] = useState("");
  const [chatMessages, setChatMessages] = useState([initialAssistantMessage]);
  const [similarTickets, setSimilarTickets] = useState([]);
  const [lastAssistantState, setLastAssistantState] = useState({});
  const [currentTicketId, setCurrentTicketId] = useState(null);
  const [conversationHistory, setConversationHistory] = useState([]);
  const [serverConversations, setServerConversations] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [notifications, setNotifications] = useState([]);
  const bottomRef = useRef(null);
  const [form, setForm] = useState({
    title: "",
    module: "",
    softwareName: "",
    softwareVersion: "",
    description: "",
    fonctionnalites: "",
    priority: "moyenne",
    phone: currentUser.phone || "",
  });
  const formValidation = validateTicketForm(form);

  useEffect(() => {
    loadTickets();
    loadServerConversations();
  }, []);

  useEffect(() => {
    async function pollNotifications() {
      try {
        const data = await fetchNotifications();
        setNotifications(data.notifications || []);
      } catch {
        // Ignore silently — l'utilisateur n'est pas bloqué si le polling échoue
      }
    }
    pollNotifications();
    const interval = setInterval(pollNotifications, 30000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const stored = readStoredClientChat(currentUser.clientId);
    if (stored) {
      const currentSnapshot = stored.current || null;
      hydrateConversation(currentSnapshot, {
        setChatSessionId,
        setChatMessages,
        setSimilarTickets,
        setLastAssistantState,
        setCurrentTicketId,
        setForm,
      });
      setConversationHistory(Array.isArray(stored.history) ? stored.history : []);
      if (currentSnapshot?.form?.phone || currentUser.phone) {
        setForm((prev) => ({
          ...prev,
          phone: ((currentSnapshot?.form?.phone) || prev.phone || currentUser.phone || "").slice(0, 10),
        }));
      }
      if (stored.page === "chatbot" || stored.page === "create") {
        setPage(stored.page);
      }
    } else {
      fetchChatHistory()
        .then((data) => {
          const msgs = Array.isArray(data.messages) ? data.messages : [];
          const serverTickets = Array.isArray(data.tickets) ? data.tickets : [];
          if (!msgs.length) return;
          const groups = groupMessagesIntoConversations(msgs);
          const entries = groups
            .map((group, i) => {
              const chatMsgs = [
                initialAssistantMessage,
                ...group.map((m) => ({ role: m.role, content: m.content })),
              ];
              const ticket = findNearestTicket(group, serverTickets);
              const firstUser = group.find((m) => m.role === "user");
              const lastMsg = group[group.length - 1];
              const reconstructedForm = ticket
                ? {
                    title: ticket.title || "",
                    module: ticket.module || "",
                    softwareName: ticket.logiciel || "",
                    softwareVersion: ticket.version || "",
                    description: ticket.details || "",
                    fonctionnalites: "",
                    priority: ticket.priority || "normale",
                    phone: "",
                  }
                : {};
              return {
                id: `server-${Date.now()}-${i}`,
                chatSessionId: "",
                title: ticket?.title || firstUser?.content?.trim().slice(0, 72) || `Conversation ${i + 1}`,
                preview: buildConversationPreview(chatMsgs),
                updatedAt: lastMsg?.timestamp || new Date().toISOString(),
                chatMessages: chatMsgs,
                similarTickets: [],
                lastAssistantState: {},
                form: reconstructedForm,
                currentTicketId: ticket?.id || null,
              };
            })
            .reverse();
          setConversationHistory(entries);
        })
        .catch(() => {});
    }
  }, [currentUser.clientId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages, similarTickets, chatLoading]);

  useEffect(() => {
    if (page === "chatbot" && chatSessionId && chatMessages.length <= 1) {
      syncSessionHistory(chatSessionId);
    }
  }, [page, chatSessionId]);

  useEffect(() => {
    if (page === "history") {
      loadServerConversations();
    }
  }, [page]);

  async function loadServerConversations() {
    setHistoryLoading(true);
    try {
      const data = await fetchConversations();
      setServerConversations(data.conversations || []);
    } catch {
      // Utilise l'historique local si l'API échoue
    } finally {
      setHistoryLoading(false);
    }
  }

  function getAllHistoryConversations() {
    const result = [];
    const seenIds = new Set();
    for (const sc of serverConversations) {
      seenIds.add(sc.id);
      if (sc.session_id) seenIds.add(sc.session_id);
      result.push({ ...sc, _source: "server" });
    }
    for (const local of conversationHistory) {
      if (!seenIds.has(local.id) && !seenIds.has(local.chatSessionId) && isMeaningfulConversation(local)) {
        result.push({
          id: local.id,
          session_id: local.chatSessionId || "",
          title: local.title,
          preview: local.preview,
          messages: (local.chatMessages || []).map((m) => ({ role: m.role, content: m.content })),
          ticket: (local.form?.title || local.currentTicketId) ? {
            id: local.currentTicketId,
            title: local.form?.title || "",
            module: local.form?.module || "",
            description: local.form?.description || "",
            softwareName: local.form?.softwareName || "",
            softwareVersion: local.form?.softwareVersion || "",
            fonctionnalites: local.form?.fonctionnalites || "",
            priority: local.form?.priority || "moyenne",
          } : null,
          updated_at: local.updatedAt,
          updatedAt: local.updatedAt,
          _source: "local",
          _snapshot: local,
        });
      }
    }
    result.sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
    return result;
  }

  function handleOpenConversationFromHistory(conv) {
    if (conv._source === "local" && conv._snapshot) {
      openArchivedConversation(conv.id);
      return;
    }
    const snapshot = {
      id: conv.id || conv.session_id || `server-${Date.now()}`,
      chatSessionId: conv.session_id || "",
      title: conv.title || "Conversation",
      preview: conv.preview || "",
      updatedAt: conv.updated_at || new Date().toISOString(),
      chatMessages: [
        initialAssistantMessage,
        ...(conv.messages || []).map((m) => ({ role: m.role, content: m.content })),
      ],
      similarTickets: [],
      lastAssistantState: {},
      form: conv.ticket
        ? {
            title: conv.ticket.title || "",
            module: conv.ticket.module || "",
            softwareName: conv.ticket.softwareName || "",
            softwareVersion: conv.ticket.softwareVersion || "",
            description: conv.ticket.description || "",
            fonctionnalites: conv.ticket.fonctionnalites || "",
            priority: conv.ticket.priority || "moyenne",
            phone: currentUser.phone || "",
          }
        : {},
      currentTicketId: conv.ticket?.id || null,
    };
    hydrateConversation(snapshot, {
      setChatSessionId,
      setChatMessages,
      setSimilarTickets,
      setLastAssistantState,
      setCurrentTicketId,
      setForm,
    });
    setChatInput("");
    setPage("chatbot");
    if (snapshot.chatSessionId) {
      syncSessionHistory(snapshot.chatSessionId);
    }
  }

  useEffect(() => {
    writeStoredClientChat(currentUser.clientId, {
      page,
      current: buildConversationSnapshot({
        chatSessionId,
        chatMessages,
        similarTickets,
        lastAssistantState,
        form,
        currentTicketId,
      }),
      history: conversationHistory,
    });
  }, [storageKey, page, chatSessionId, chatMessages, similarTickets, lastAssistantState, form, conversationHistory]);

  async function loadTickets() {
    try {
      const data = await fetchClientTickets();
      setTickets(data.tickets || []);
      setStats(data.stats || {});
    } catch {
      setMessage("Impossible de charger les tickets client.");
    }
  }

  const [deleteConfirm, setDeleteConfirm] = useState(null);
  const [clientReply, setClientReply] = useState("");
  const [clientReplySending, setClientReplySending] = useState(false);

  async function handleClientReply(ticketId) {
    if (!clientReply.trim()) return;
    setClientReplySending(true);
    try {
      const res = await replyToTicket(ticketId, clientReply);
      setClientReply("");
      setTickets((prev) => prev.map((tk) => tk.id === ticketId ? res.ticket : tk));
    } catch (err) {
      setMessage(err.message || "Erreur lors de l'envoi du message.");
    } finally {
      setClientReplySending(false);
    }
  }

  async function handleDeleteTicket(ticketId, title) {
    setDeleteConfirm({ ticketId, title });
  }

  async function confirmDelete() {
    if (!deleteConfirm) return;
    try {
      await deleteClientTicket(deleteConfirm.ticketId);
      setSelectedClientTicketId(null);
      setDeleteConfirm(null);
      await loadTickets();
    } catch (err) {
      setDeleteConfirm(null);
      setMessage(err.message || "Erreur lors de la suppression du ticket.");
    }
  }

  function setField(name, value) {
    setForm((prev) => ({ ...prev, [name]: value }));
  }

  function openCreateForm() {
    setPage("create");
  }

  function openChatbot(prefill = "") {
    const latestUserMessage = [...chatMessages].reverse().find((item) => item.role === "user")?.content?.trim() || "";
    const normalizedPrefill = prefill.trim();

    setPage("chatbot");
    if (normalizedPrefill) {
      setChatInput(normalizedPrefill);
      if (normalizedPrefill !== latestUserMessage) {
        setLastAssistantState({});
        setSimilarTickets([]);
      }
    } else if (!chatMessages.length) {
      setChatMessages([initialAssistantMessage]);
    }
  }

  function archiveCurrentConversation() {
    const snapshot = buildConversationSnapshot({
      chatSessionId,
      chatMessages,
      similarTickets,
      lastAssistantState,
      form,
      currentTicketId,
    });
    if (!isMeaningfulConversation(snapshot)) return;

    setConversationHistory((prev) => {
      const filtered = prev.filter(
        (item) => item.id !== snapshot.id && item.chatSessionId !== snapshot.chatSessionId
      );
      return [snapshot, ...filtered].slice(0, 12);
    });
  }

  function startFreshConversation() {
    setChatSessionId("");
    setChatMessages([initialAssistantMessage]);
    setChatInput("");
    setSimilarTickets([]);
    setLastAssistantState({});
    setCurrentTicketId(null);
  }

  function resetChatbot() {
    archiveCurrentConversation();
    startFreshConversation();
  }

  function openArchivedConversation(conversationId) {
    const target = conversationHistory.find((item) => item.id === conversationId);
    if (!target) return;

    const currentSnapshot = buildConversationSnapshot({
      chatSessionId,
      chatMessages,
      similarTickets,
      lastAssistantState,
      form,
      currentTicketId,
    });

    setConversationHistory((prev) => {
      const withoutTarget = prev.filter((item) => item.id !== conversationId);
      if (isMeaningfulConversation(currentSnapshot) && currentSnapshot.id !== conversationId) {
        return [currentSnapshot, ...withoutTarget].slice(0, 12);
      }
      return withoutTarget;
    });

    hydrateConversation(target, {
      setChatSessionId,
      setChatMessages,
      setSimilarTickets,
      setLastAssistantState,
      setCurrentTicketId,
      setForm,
    });
    setChatInput("");
    setPage("chatbot");
    if (target.chatSessionId) {
      syncSessionHistory(target.chatSessionId);
    }
  }

  async function syncSessionHistory(sessionId) {
    if (!sessionId) return;
    try {
      const data = await fetchConversationSession(sessionId);
      const history = Array.isArray(data.history) ? data.history : [];
      const hydratedState = applyFormHintsToAssistantState(data.state || {}, form);
      setChatMessages((prev) => {
        if (!history.length) {
          return prev.length ? prev : [initialAssistantMessage];
        }

        const hydrated = history.map((item) => ({
          role: item.role,
          content: item.content,
          state: item.role === "assistant" ? hydratedState : undefined,
        }));

        return hydrated.length ? hydrated : [initialAssistantMessage];
      });
      setLastAssistantState(hydratedState);
    } catch {
      // Ignore session hydration failures and keep current local chat state.
    }
  }

  async function submitChatMessage(textFromSuggestion = "") {
    const content = (textFromSuggestion || chatInput).trim();
    if (!content || chatLoading) return;

    // On envoie le contenu brut, le ticket_context fournit déjà module/logiciel/version
    const backendQuestion = content;

    // Contexte du ticket pour que le backend connaisse module/logiciel/version à chaque message
    const ticketCtx = form.softwareName ? {
      title: form.title || "",
      module: form.module || "",
      software: form.softwareName || "",
      version: form.softwareVersion || "",
      priority: form.priority || "",
      description: form.description || "",
      fonctionnalites: form.fonctionnalites || "",
    } : {};

    const userMessage = { role: "user", content };
    setChatMessages((prev) => [...prev, userMessage]);
    setChatInput("");
    setChatLoading(true);
    setMessage("");

    try {
      const response = await sendMessage({
        session_id: chatSessionId,
        question: backendQuestion,
        ticket_context: ticketCtx,
      });

      const state = applyFormHintsToAssistantState(response.state || {}, form);
      const assistantMessage = {
        role: "assistant",
        content: response.answer,
        state,
      };

      setChatSessionId(response.session_id || chatSessionId);
      setChatMessages((prev) => [...prev, assistantMessage]);
      setLastAssistantState(state);
      setSimilarTickets(
        (state.tickets_similaires || [])
          .filter((ticket) => (ticket.similarity || 0) >= MIN_USEFUL_SIMILARITY)
          .map((ticket) => ({
            ...ticket,
            description: ticket.objet,
            selectedModule: form.module || "",
            module: ticket.module || state.module || "",
            type: ticket.type || state.type_incident || "",
            solution: ticket.solution || "",
          }))
      );
      setForm((prev) => ({
        ...prev,
        title: prev.title || content.slice(0, 90),
        module: state.module || prev.module,
        description: prev.description || content,
      }));
      if (!chatSessionId && response.session_id) {
        syncSessionHistory(response.session_id);
      }
    } catch {
      setChatMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Le chatbot ne repond pas pour le moment. Tu peux quand meme finaliser le ticket manuellement.",
        },
      ]);
    } finally {
      setChatLoading(false);
    }
  }

  async function submitTicket() {
    if (!formValidation.isValid) {
      setMessage("Veuillez remplir tous les champs obligatoires. La description doit contenir au moins 5 mots.");
      return;
    }
    setSending(true);
    setMessage("");
    try {
      archiveCurrentConversation();
      const res = await createClientTicket({
        title: form.title,
        module: form.module,
        software_name: form.softwareName,
        software_version: form.softwareVersion,
        description: form.description,
        fonctionnalites: form.fonctionnalites,
        priority: form.priority,
        phone: form.phone,
        requester_name: currentUser.name,
        client_name: currentUser.clientName,
        client_id: currentUser.clientId,
        site: "Alger",
      });
      await loadTickets();
      setMessage(`Ticket #${res.ticket.id} cree avec succes.`);
      setCurrentTicketId(res.ticket.id);
      const submittedDescription = form.description;
      const submittedTitle = form.title;
      const submittedModule = form.module;
      const submittedSoftwareName = form.softwareName;
      const submittedSoftwareVersion = form.softwareVersion;
      const submittedFonctionnalites = form.fonctionnalites;
      const submittedPriority = form.priority;
      const submittedPhone = form.phone;
      setForm({
        title: "",
        module: "",
        softwareName: "",
        softwareVersion: "",
        description: "",
        fonctionnalites: "",
        priority: "moyenne",
        phone: currentUser.phone || "",
      });
      const createdTicketUserMessage = {
        role: "user",
        content: submittedDescription || submittedTitle,
      };
      const bootstrapMessage = {
        role: "assistant",
        content:
          res.assistant?.answer ||
          `Ticket #${res.ticket.id} cree. Analyse en cours sur ${submittedSoftwareName} v${submittedSoftwareVersion}...`,
        state: applyFormHintsToAssistantState(res.assistant?.state || {}, {
          ...form,
          module: submittedModule,
        }),
      };
      // Message d'accueil contextuel : l'agent sait déjà ce que le client a saisi
      const contextualWelcome = {
        role: "assistant",
        content: `Bonjour ${currentUser?.name ? currentUser.name.split(" ")[0] : ""}. J'ai bien recu votre ticket #${res.ticket.id} concernant ${submittedSoftwareName} v${submittedSoftwareVersion}, module ${submittedModule}. J'analyse votre probleme...`,
      };
      setChatMessages([contextualWelcome, createdTicketUserMessage, bootstrapMessage]);
      setChatSessionId(res.assistant?.session_id || "");
      setSimilarTickets(
        ((bootstrapMessage.state?.tickets_similaires) || [])
          .filter((ticket) => (ticket.similarity || 0) >= MIN_USEFUL_SIMILARITY)
          .map((ticket) => ({
            ...ticket,
            description: ticket.objet,
            selectedModule: submittedModule || "",
            module: ticket.module || bootstrapMessage.state?.module || "",
            type: ticket.type || bootstrapMessage.state?.type_incident || "",
            solution: ticket.solution || "",
          }))
      );
      setLastAssistantState(bootstrapMessage.state || {});
      setForm((prev) => ({
        ...prev,
        title: submittedTitle,
        module: res.assistant?.state?.module || submittedModule,
        softwareName: submittedSoftwareName,
        softwareVersion: submittedSoftwareVersion,
        description: submittedDescription,
        fonctionnalites: submittedFonctionnalites,
        priority: submittedPriority,
        phone: submittedPhone,
      }));
      setPage("chatbot");
    } catch (error) {
      setMessage(error.message || "Erreur lors de la creation du ticket.");
    } finally {
      setSending(false);
    }
  }

  const latestAssistantMessage = [...chatMessages].reverse().find((item) => item.role === "assistant");
  const readyToAssign =
    Boolean(lastAssistantState.ready_for_assignment) ||
    /une fois confirme,\s*votre ticket sera assigne a un technicien/i.test(latestAssistantMessage?.content || "");
  const solutionProposed =
    lastAssistantState.statut === "solution_proposee" &&
    Boolean((lastAssistantState.solution_proposee || "").trim() || similarTickets.length);
  const chatLocked = readyToAssign || solutionProposed || lastAssistantState.statut === "attribue";

  async function assignTicketToTechnician() {
    if (!currentTicketId || sending) return;
    setSending(true);
    setMessage("");
    try {
      const res = await assignClientTicket({ ticket_id: currentTicketId });
      await loadTickets();
      setMessage(res.message || `Ticket #${currentTicketId} assigne a un technicien.`);
      setLastAssistantState((prev) => ({
        ...prev,
        ready_for_assignment: false,
        statut: "attribue",
      }));
      setChatMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: res.message || `Ticket #${currentTicketId} assigne a un technicien.`,
          state: {
            ...lastAssistantState,
            ready_for_assignment: false,
            statut: "attribue",
          },
        },
      ]);
    } catch (error) {
      setMessage(error.message || "Erreur lors de l'affectation du ticket.");
    } finally {
      setSending(false);
    }
  }

  const [clientSearch, setClientSearch] = useState("");
  const deferredClientSearch = useDeferredValue(clientSearch);
  const filtered = tickets
    .filter((item) => {
      if (deferredTab === "tous") return true;
      if (deferredTab === "en_attente") return item.status === "en_attente" || item.status === "ouvert";
      return item.status === deferredTab;
    })
    .filter((item) => {
      const q = deferredClientSearch.toLowerCase().trim();
      if (!q) return true;
      return (
        (item.title || "").toLowerCase().includes(q) ||
        (item.category || "").toLowerCase().includes(q) ||
        String(item.id || "").includes(q) ||
        (item.description || "").toLowerCase().includes(q)
      );
    });

  return (
    <div className="client-shell">
      {deleteConfirm && (
        <div className="modal-overlay" onClick={() => setDeleteConfirm(null)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <div className="modal-icon modal-icon-danger">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>
              </svg>
            </div>
            <h3 className="modal-title">Supprimer ce ticket ?</h3>
            <p className="modal-desc">
              {deleteConfirm.title && (
                <><strong>"{deleteConfirm.title}"</strong><br /></>
              )}
              <span className="modal-ticket-id">#{deleteConfirm.ticketId}</span>
              <br /><br />
              Cette suppression est <strong>definitive</strong>.<br />Le ticket ne pourra pas etre recupere.
            </p>
            <div className="modal-actions">
              <button type="button" className="modal-btn-cancel" onClick={() => setDeleteConfirm(null)}>
                Annuler
              </button>
              <button type="button" className="modal-btn-danger" onClick={confirmDelete}>
                Supprimer
              </button>
            </div>
          </div>
        </div>
      )}
      <header className="client-topbar">
        <div className="client-brand">
          <div className="client-brand-mark">BIG</div>
          <div>
            <strong>Informatique</strong>
            <span>Support client BIG</span>
          </div>
        </div>
        <nav className="client-nav">
          <button type="button" className={`client-nav-link${page === "tickets" ? " active" : ""}`} onClick={() => { if (page === "chatbot") archiveCurrentConversation(); setPage("tickets"); }}>Mes Tickets</button>
          <button type="button" className={`client-nav-link${(page === "history" || page === "chatbot") ? " active" : ""}`} onClick={() => setPage("history")}>Assistant IA</button>
        </nav>
        <div className="client-user">
          <NotificationBell
            notifications={notifications}
            onNotificationClick={(ticketId) => {
              if (page === "chatbot") archiveCurrentConversation();
              setPage("tickets");
              setSelectedClientTicketId(String(ticketId));
            }}
            onMarkAllRead={() =>
              setNotifications((prev) => prev.map((n) => ({ ...n, isRead: true })))
            }
            onNotificationRead={(id) =>
              setNotifications((prev) =>
                prev.map((n) => (n.id === id ? { ...n, isRead: true } : n))
              )
            }
          />
          <div className="client-avatar">{currentUser.initials}</div>
          <div>
            <strong>{currentUser.name}</strong>
            <span>{currentUser.role}</span>
          </div>
          <button type="button" className="topbar-logout" onClick={onLogout}>Deconnexion</button>
        </div>
      </header>

      <main className="client-main">
        <div className="client-actions">
          <button type="button" className={page === "tickets" ? "client-main-tab active" : "client-main-tab"} onClick={() => setPage("tickets")}>
            Mes Tickets
          </button>
          <button type="button" className={(page === "create" || page === "chatbot") ? "client-main-tab active light" : "client-main-tab light"} onClick={openCreateForm} style={{ display: page === "history" ? "none" : undefined }}>
            Creer un Nouveau Ticket
          </button>
        </div>

        {page === "tickets" ? (
          <>
            <section className="client-hero">
              <div className="client-hero-copy">
                <p className="client-hero-label">Support Client BIG</p>
                <h1>Suivi du Support Client</h1>
                <p><strong>Bonjour {currentUser.name.split(" ")[0]} !</strong> Bienvenue sur la plateforme de support client BIG Informatique</p>
                <div className="client-hero-tags">
                  <span>Service disponible</span>
                  <span>Priorisation automatique</span>
                  <span>Suivi en temps reel</span>
                </div>
              </div>
              <div className="client-hero-illustration"><MailOutline /></div>
            </section>

            <section className="client-stats">
              <ClientStatCard label="Tickets inseres" value={stats.total} tone="yellow" icon={<CalendarOutline />} />
              <ClientStatCard label="Tickets en attente" value={stats.enAttente} tone="blue" icon={<MailOutline />} />
              <ClientStatCard label="Tickets resolus" value={stats.resolus} tone="green" icon={<CheckOutline />} />
            </section>

            <section className="workspace-grid client-workspace">
              {/* ── Colonne gauche : liste ── */}
              <aside className="queue-panel">
                <div className="panel-head">
                  <div>
                    <p className="section-kicker">Mes demandes</p>
                    <h2>Tickets recents</h2>
                  </div>
                  <button type="button" className="primary-action" onClick={openCreateForm}>+ Nouveau</button>
                </div>
                <div className="toolbar">
                  <input
                    className="search-input"
                    value={clientSearch}
                    onChange={(e) => setClientSearch(e.target.value)}
                    placeholder="Rechercher par titre, categorie, n° ticket..."
                  />
                  <div className="tab-row">
                    {clientTabs.map((item) => (
                      <button key={item.key} type="button" className={`tab-chip${tab === item.key ? " active" : ""}`} onClick={() => setTab(item.key)}>
                        {item.label} ({countClientTab(item.key, stats)})
                      </button>
                    ))}
                  </div>
                </div>
                <div className="queue-list">
                  {filtered.length === 0 ? (
                    <p style={{ color: "#8a9bbf", textAlign: "center", padding: "24px 0" }}>
                      {clientSearch ? "Aucun ticket ne correspond à votre recherche." : "Aucun ticket pour l'instant."}
                    </p>
                  ) : filtered.map((ticket) => (
                    <button
                      key={ticket.id}
                      type="button"
                      className={`queue-item${selectedClientTicketId === ticket.id ? " selected" : ""}`}
                      onClick={() => setSelectedClientTicketId(ticket.id === selectedClientTicketId ? null : ticket.id)}
                    >
                      <div className="queue-top">
                        <strong>#{ticket.id}</strong>
                        <span className={`badge ${ticket.priority}`}>{priorityLabel(ticket.priority)}</span>
                      </div>
                      <h3>{ticket.title}</h3>
                      <p>{ticket.category}</p>
                      <div className="queue-bottom">
                        <span>{ticket.createdAgo}</span>
                        <span className={`status-tag ${ticket.status}`}>{clientStatusLabel(ticket.status)}</span>
                      </div>
                    </button>
                  ))}
                </div>
              </aside>

              {/* ── Colonne droite : détail ── */}
              <section className="detail-stack">
                {selectedClientTicketId && (() => {
                  const t = tickets.find((tk) => tk.id === selectedClientTicketId);
                  if (!t) return null;
                  return (
                    <>
                      <article className="detail-card main-detail">
                        <div className="detail-head">
                          <div>
                            <p className="section-kicker">Ticket #{t.id}</p>
                            <h2>{t.title}</h2>
                            <p style={{ color: "#7a90b8", marginTop: 4, fontSize: 14 }}>{t.category} • {t.requesterName}</p>
                          </div>
                          <div className="detail-badges">
                            <span className={`badge ${t.priority}`}>{priorityLabel(t.priority)}</span>
                            <span className={`status-tag ${t.status}`}>{clientStatusLabel(t.status)}</span>
                          </div>
                        </div>
                        <div className="detail-meta-grid">
                          <Info label="Logiciel" value={t.softwareName || "Non renseigne"} />
                          <Info label="Version" value={t.softwareVersion || "Non renseignee"} />
                          <Info label="Module" value={t.category?.split(" / ")[0] || "—"} />
                          <Info label="Type" value={t.category?.split(" / ")[1] || "—"} />
                          <Info label="Cree" value={t.createdAgo} />
                          <Info label="Telephone" value={t.phone || "—"} />
                          {t.assignedTo && (
                            <Info label="Technicien assigne" value={t.assignedTo} />
                          )}
                        </div>
                        <div className="summary-box">
                          <strong>Description du probleme</strong>
                          <p>{t.cleanDescription || t.description || "Aucune description fournie."}</p>
                        </div>
                        {t.assignedTo && (
                          <div className="tech-conversation">
                            <div className="tech-conv-head">
                              <strong>Discussion avec le technicien</strong>
                              <span className="tech-conv-name">{t.assignedTo}</span>
                            </div>
                            {t.conversation && t.conversation.length > 0 ? (
                              <div className="tech-conv-messages">
                                {t.conversation.map((msg, idx) => (
                                  <div key={idx} className={`tech-conv-bubble ${msg.role}`}>
                                    <span className="tech-conv-author">{msg.author}</span>
                                    <p>{msg.text}</p>
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <p className="tech-conv-empty">En attente de la premiere reponse du technicien.</p>
                            )}
                            {t.status !== "resolu" && (
                              <div className="tech-conv-input-row">
                                <input
                                  type="text"
                                  className="tech-conv-input"
                                  value={clientReply}
                                  onChange={(e) => setClientReply(e.target.value)}
                                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleClientReply(t.id); } }}
                                  placeholder="Repondre au technicien..."
                                  disabled={clientReplySending}
                                />
                                <button
                                  type="button"
                                  className="tech-conv-send"
                                  onClick={() => handleClientReply(t.id)}
                                  disabled={!clientReply.trim() || clientReplySending}
                                >
                                  {clientReplySending ? "..." : "Envoyer"}
                                </button>
                              </div>
                            )}
                          </div>
                        )}
                        <div className="action-row">
                          {t.status !== "attribue" && t.status !== "resolu" && (
                            <button
                              type="button"
                              className="primary-action"
                              onClick={() => {
                                setForm((prev) => ({
                                  ...prev,
                                  title: t.title || "",
                                  module: t.category?.split(" / ")[0]?.toLowerCase() || "",
                                  softwareName: t.softwareName || "",
                                  softwareVersion: t.softwareVersion || "",
                                  description: t.description || "",
                                  priority: t.priority || "moyenne",
                                  phone: t.phone || prev.phone,
                                }));
                                setPage("create");
                              }}
                            >
                              Modifier le ticket
                            </button>
                          )}
                          <button type="button" className="secondary-action" onClick={() => setSelectedClientTicketId(null)}>
                            Fermer
                          </button>
                          {t.status !== "attribue" && t.status !== "resolu" && (
                            <button
                              type="button"
                              className="secondary-action"
                              style={{ color: "#c0392b" }}
                              onClick={() => handleDeleteTicket(t.id, t.title)}
                            >
                              Supprimer
                            </button>
                          )}
                        </div>
                      </article>

                      <div className="detail-columns">
                        <article className="detail-card">
                          <div className="small-head">
                            <div>
                              <p className="section-kicker">Assistant IA</p>
                              <h3>Suggestions de solutions</h3>
                            </div>
                          </div>
                          <ul className="bullet-list">
                            <li>Verifiez les parametres du module {t.category?.split(" / ")[0] || ""} dans la configuration</li>
                            <li>Consultez la base de connaissances pour des cas similaires</li>
                            <li>Contactez le support si le probleme persiste</li>
                          </ul>
                        </article>
                        <article className="detail-card">
                          <div className="small-head">
                            <div>
                              <p className="section-kicker">Suivi</p>
                              <h3>Etat de traitement</h3>
                            </div>
                          </div>
                          <div className="check-list">
                            <label className={`check-item${["attribue","resolu"].includes(t.status) ? " done" : ""}`}>
                              <input type="checkbox" checked={["attribue","resolu"].includes(t.status)} readOnly />
                              <span>Ticket recu et enregistre</span>
                            </label>
                            <label className={`check-item${t.status === "attribue" || t.status === "resolu" ? " done" : ""}`}>
                              <input type="checkbox" checked={t.status === "attribue" || t.status === "resolu"} readOnly />
                              <span>Affecte a un technicien</span>
                            </label>
                            <label className={`check-item${t.status === "resolu" ? " done" : ""}`}>
                              <input type="checkbox" checked={t.status === "resolu"} readOnly />
                              <span>Probleme resolu</span>
                            </label>
                          </div>
                        </article>
                      </div>
                    </>
                  );
                })()}
                {!selectedClientTicketId && (
                  <article className="detail-card main-detail" style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: 220, color: "#8a9bbf", textAlign: "center", gap: 12 }}>
                    <MailOutline />
                    <p style={{ fontSize: 15 }}>Selectionnez un ticket pour voir ses details</p>
                  </article>
                )}
              </section>
            </section>
          </>
        ) : page === "create" ? (
          <section className="create-ticket-layout single-column">
            <article className="client-panel create-ticket-panel">
              <div className="create-ticket-head">
                <div>
                  <p className="client-hero-label">Nouvelle demande</p>
                  <h2>Creer un Nouveau Ticket</h2>
                  <p>Remplis le formulaire puis envoie le ticket. Des que le ticket est cree, la conversation avec l'agent IA continue automatiquement.</p>
                </div>
                <button type="button" className="secondary-action" onClick={() => setPage("tickets")}>Retour aux tickets</button>
              </div>
              <div className="create-ticket-grid">
                <Field label="Titre du ticket" required error={formValidation.errors.title}>
                  <input value={form.title} onChange={(e) => setField("title", e.target.value)} placeholder="Ex: Erreur SQL sur le module stock" />
                </Field>
                <Field label="Module concerne" required error={formValidation.errors.module}>
                  <select className="field-select" value={form.module} onChange={(e) => setField("module", e.target.value)}>
                    <option value="" disabled>Choisis ton module</option>
                    <optgroup label="Finance">
                      <option value="comptabilite">Comptabilité</option>
                      <option value="immobilisations">Immobilisations</option>
                      <option value="tresorerie">Trésorerie</option>
                      <option value="fiscalite">Fiscalité</option>
                      <option value="budget">Budget</option>
                      <option value="analytique">Analytique</option>
                      <option value="facturation">Facturation</option>
                    </optgroup>
                    <optgroup label="Paie et RH">
                      <option value="paie">Paie</option>
                      <option value="rh">Gestion Ressources Humaines</option>
                      <option value="gestion_temps">Gestion du Temps</option>
                      <option value="administration">Administration</option>
                    </optgroup>
                    <optgroup label="Gestion Commerciale">
                      <option value="achats">Achats</option>
                      <option value="stock">Stock</option>
                      <option value="ventes">Ventes</option>
                      <option value="cimenterie">Cimenterie</option>
                    </optgroup>
                    <optgroup label="BIGSoft 8i">
                      <option value="plateforme_java">Plateforme java</option>
                      <option value="sav">Service Après Vente</option>
                      <option value="crm">CRM</option>
                      <option value="marches">Marchés</option>
                      <option value="gpao">GPAO</option>
                      <option value="qualite">Qualité</option>
                      <option value="gestion_projets">Gestion de projets</option>
                      <option value="gestion_taches">Gestion des tâches</option>
                      <option value="gestion_flotte">Gestion de flotte</option>
                    </optgroup>
                    <optgroup label="BIGMARPI">
                      <option value="gestion_marches">Gestion des Marchés</option>
                      <option value="gestion_immobiliere">Gestion Immobilière</option>
                      <option value="suivi_realisation">Suivi Réalisation</option>
                      <option value="gestion_location">Gestion Location</option>
                      <option value="gestion_documents">Gestion des Documents</option>
                    </optgroup>
                    <optgroup label="Autres logiciels">
                      <option value="bigsmq">BIGSMQ</option>
                      <option value="bigtrans">BIGTrans</option>
                      <option value="bigpharm">BIGPharm</option>
                      <option value="bigclinic">BIGClinic</option>
                      <option value="bigmed">BIGMed</option>
                      <option value="bighotel">BIGHotel</option>
                      <option value="bigloc">BIGLoc</option>
                      <option value="alsem">ALSEM</option>
                      <option value="dynamic_reports">Dynamic Big Reports</option>
                      <option value="tickets_support">Gestion des Tickets de Support</option>
                      <option value="bigcom">BIGCom</option>
                    </optgroup>
                    <optgroup label="Mobile">
                      <option value="mobile">Mobile</option>
                      <option value="bigcrm_mobile">BIGCRM Mobile</option>
                      <option value="bigdashboard_mobile">BIGDashboard Mobile</option>
                      <option value="bigmarpi_mobile">BIGMarpi Mobile</option>
                      <option value="bigimmo_mobile">BIGImmo Mobile</option>
                      <option value="biginventaire_mobile">BIGInventaire Mobile</option>
                      <option value="demandesrh_mobile">DemandesRH Mobile</option>
                      <option value="biglivraison_mobile">BIGLivraison Mobile</option>
                      <option value="bighelpdesk_mobile">BIGHelpdesk Mobile</option>
                      <option value="bigclinique_mobile">BIGClinique Mobile</option>
                      <option value="bigsmq_mobile">BIGSMQ Mobile</option>
                      <option value="bigmed_mobile">BIGMED Mobile</option>
                    </optgroup>
                    <optgroup label="Interventions">
                      <option value="interventions_annaba">Interventions Annaba</option>
                      <option value="interventions_alger">Interventions Alger</option>
                      <option value="interventions_oran">Interventions Oran</option>
                    </optgroup>
                  </select>
                </Field>
              </div>
              <div className="create-ticket-grid">
                <Field label="Nom du logiciel" required error={formValidation.errors.softwareName}>
                  <input value={form.softwareName} onChange={(e) => setField("softwareName", e.target.value)} placeholder="Ex : BIG Paie, BIG Gestion, BIG RH" />
                </Field>
                <Field label="Version du logiciel" required error={formValidation.errors.softwareVersion}>
                  <input value={form.softwareVersion} onChange={(e) => setField("softwareVersion", e.target.value)} placeholder="Ex : 7.0.2.G" />
                </Field>
              </div>
              <Field
                label="Description du probleme"
                required
                error={formValidation.errors.description}
                help={`Minimum 5 mots. Actuel : ${countWords(form.description)} mot(s).`}
              >
                <textarea value={form.description} onChange={(e) => setField("description", e.target.value)} rows={8} placeholder="Decrivez le probleme rencontre, le message d'erreur, le module concerne et ce que vous avez deja essaye." />
              </Field>
              <Field
                label="Fonctionnalites concernees"
                help="Selectionnez les fonctionnalites liees a votre probleme (filtre selon le module choisi)"
              >
                <FonctionnalitesPicker
                  module={form.module}
                  value={form.fonctionnalites}
                  onChange={(val) => setField("fonctionnalites", val)}
                />
              </Field>
              <div className="create-ticket-grid">
                <Field label="Priorite">
                  <select className="field-select" value={form.priority} onChange={(e) => setField("priority", e.target.value)}>
                    <option value="normale">Faible</option><option value="moyenne">Moyenne</option><option value="haute">Haute</option><option value="urgente">Critique</option>
                  </select>
                </Field>
                <Field
                  label="Telephone de contact"
                  required
                  error={formValidation.errors.phone}
                  help="Saisir exactement 10 chiffres. Exemple : 0550000000"
                >
                  <input value={form.phone} onChange={(e) => setField("phone", e.target.value.replace(/\D/g, "").slice(0, 10))} inputMode="numeric" maxLength={10} placeholder="Ex : 0550000000" />
                </Field>
              </div>
              {message ? <p className="field-help">{message}</p> : null}
              <div className="action-row create-actions">
                <button type="button" className="secondary-action" onClick={() => setPage("tickets")}>Annuler</button>
                <button
                  type="button"
                  className="primary-action"
                  disabled={!formValidation.isValid || sending}
                  onClick={submitTicket}
                >
                  {sending ? "Analyse en cours..." : "Qualifier avec l'assistant IA"}
                </button>
              </div>
            </article>
          </section>
        ) : page === "history" ? (
          <section className="chatbot-ticket-layout">
            <article className="client-panel chatbot-panel">
              <div className="create-ticket-head">
                <div>
                  <p className="client-hero-label">Assistant IA</p>
                  <h2>Mes Conversations</h2>
                  <p>Selectionnez une conversation pour la consulter ou la continuer avec l'agent IA.</p>
                </div>
                <button type="button" className="secondary-action" onClick={() => setPage("tickets")}>
                  Retour aux tickets
                </button>
              </div>

              {historyLoading ? (
                <p style={{ color: "#8a9bbf", padding: "24px 0", textAlign: "center" }}>Chargement des conversations...</p>
              ) : getAllHistoryConversations().length === 0 ? (
                <div className="similar-box" style={{ marginTop: 16 }}>
                  <strong>Aucune conversation</strong>
                  <p>Vos conversations avec l'assistant apparaitront ici. Creez un ticket pour demarrer.</p>
                </div>
              ) : (
                <div className="assistant-history-list">
                  {getAllHistoryConversations().map((conv) => (
                    <button
                      key={conv.id}
                      type="button"
                      className="assistant-history-item"
                      onClick={() => handleOpenConversationFromHistory(conv)}
                    >
                      <strong>{conv.title || "Conversation"}</strong>
                      {(conv.ticket?.module || conv.ticket?.softwareName) ? (
                        <span className="history-meta">
                          {[conv.ticket.module, conv.ticket.softwareName, conv.ticket.softwareVersion].filter(Boolean).join(" · ")}
                        </span>
                      ) : null}
                      <span>{conv.preview || ""}</span>
                      <small>{formatConversationDate(conv.updated_at || conv.updatedAt)}</small>
                    </button>
                  ))}
                </div>
              )}
            </article>

            <aside className="client-panel create-help-panel chatbot-side-panel">
              <p className="client-hero-label">Nouveau ticket</p>
              <h3>Demarrer une conversation</h3>
              <div className="similar-box">
                <strong>Creez un ticket pour demarrer</strong>
                <p>Pour commencer une nouvelle conversation avec l'assistant IA, remplissez le formulaire de ticket.</p>
              </div>
              <div className="action-row create-actions">
                <button type="button" className="primary-action" onClick={openCreateForm}>
                  Nouveau ticket
                </button>
              </div>
            </aside>
          </section>
        ) : (
          <section className="chatbot-ticket-layout">
            <article className="client-panel chatbot-panel">
              <div className="create-ticket-head">
                <div>
                  <p className="client-hero-label">Assistant ticketing</p>
                  <h2>Chatbot Support</h2>
                  <p>Conversation en cours avec l'agent IA. Le resume du ticket est visible a droite.</p>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button type="button" className="secondary-action" onClick={() => setPage("history")}>Ancienne conversation</button>
                </div>
              </div>

              {form.title && (
                <div className="ticket-context-banner">
                  <div className="ticket-context-main">
                    <strong>{form.title}</strong>
                    {currentTicketId && <span className="ticket-id-badge">#{currentTicketId}</span>}
                  </div>
                  <div className="ticket-context-meta">
                    {form.module && <span>Module : {form.module}</span>}
                    {form.softwareName && (
                      <span>{form.softwareName}{form.softwareVersion ? ` v${form.softwareVersion}` : ""}</span>
                    )}
                    {form.description && (
                      <span className="ticket-context-desc">{form.description.slice(0, 100)}{form.description.length > 100 ? "…" : ""}</span>
                    )}
                  </div>
                </div>
              )}

              <div className="chatbot-shell">
                <div className="chatbot-header">
                  <div>
                    <strong>Assistant Support BIG</strong>
                    <span>
                      {chatLoading
                        ? "En train de répondre..."
                        : lastAssistantState?.statut === "solution_proposee"
                        ? "✓ Solution proposée"
                        : lastAssistantState?.statut === "escalade_technique"
                        ? "Transfert vers un technicien"
                        : lastAssistantState?.statut === "resolu"
                        ? "✓ Résolu"
                        : "En ligne"}
                    </span>
                  </div>
                </div>

                <ChatWindow
                  messages={chatMessages}
                  loading={chatLoading}
                  bottomRef={bottomRef}
                  similarTickets={similarTickets}
                />

                {readyToAssign && (
                  <div style={{ padding: "8px 16px", background: "#f0fdf4", borderTop: "1px solid #bbf7d0", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                    <span style={{ fontSize: 13, color: "#15803d" }}>✓ Votre ticket est prêt à être assigné à un technicien.</span>
                    <button
                      type="button"
                      className="primary-action"
                      style={{ flexShrink: 0 }}
                      disabled={!currentTicketId || sending}
                      onClick={assignTicketToTechnician}
                    >
                      {sending ? "Assignation..." : "Assigner"}
                    </button>
                  </div>
                )}
                <div className="chatbot-input-row">
                  <textarea
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    placeholder="Répondez ici..."
                    rows={3}
                    disabled={chatLoading || lastAssistantState.statut === "attribue"}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        submitChatMessage();
                      }
                    }}
                  />
                  <button
                    type="button"
                    className="primary-action"
                    disabled={chatLoading || !chatInput.trim() || lastAssistantState.statut === "attribue"}
                    onClick={() => submitChatMessage()}
                  >
                    {chatLoading ? "..." : "Envoyer"}
                  </button>
                </div>
              </div>
            </article>

            <aside className="client-panel create-help-panel chatbot-side-panel">
              <p className="client-hero-label">Résumé du ticket</p>
              <h3>{form.title || "Ticket en cours"}</h3>

              <div className="similar-box">
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                  <tbody>
                    {currentTicketId && (
                      <tr>
                        <td style={tdLabel}>Numéro</td>
                        <td style={tdValue}>#{currentTicketId}</td>
                      </tr>
                    )}
                    {form.module && (
                      <tr>
                        <td style={tdLabel}>Module</td>
                        <td style={tdValue}>{form.module}</td>
                      </tr>
                    )}
                    {form.softwareName && (
                      <tr>
                        <td style={tdLabel}>Logiciel</td>
                        <td style={tdValue}>{form.softwareName}</td>
                      </tr>
                    )}
                    {form.softwareVersion && (
                      <tr>
                        <td style={tdLabel}>Version</td>
                        <td style={tdValue}>{form.softwareVersion}</td>
                      </tr>
                    )}
                    {form.priority && (
                      <tr>
                        <td style={tdLabel}>Priorité</td>
                        <td style={tdValue}>{priorityLabel(form.priority)}</td>
                      </tr>
                    )}
                    {(lastAssistantState.type_incident) && (
                      <tr>
                        <td style={tdLabel}>Type</td>
                        <td style={tdValue}>{lastAssistantState.type_incident}</td>
                      </tr>
                    )}
                    {form.fonctionnalites && (
                      <tr>
                        <td style={tdLabel}>Fonctionnalités</td>
                        <td style={tdValue}>{form.fonctionnalites}</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              {form.description && (
                <div className="similar-box">
                  <strong style={{ fontSize: 12, color: "#6b7280", display: "block", marginBottom: 4 }}>Description</strong>
                  <p style={{ fontSize: 13, margin: 0 }}>{form.description.slice(0, 220)}{form.description.length > 220 ? "…" : ""}</p>
                </div>
              )}

              {lastAssistantState.solution_proposee && (
                <div className="similar-box" style={{ borderLeft: "3px solid #22c55e" }}>
                  <strong style={{ color: "#16a34a", fontSize: 12 }}>✓ Solution proposée</strong>
                  <p style={{ fontSize: 13, margin: "4px 0 0" }}>{lastAssistantState.solution_proposee}</p>
                </div>
              )}

              <div className="action-row create-actions">
                <button type="button" className="secondary-action" onClick={openCreateForm}>Modifier</button>
                <button type="button" className="primary-action" onClick={() => { archiveCurrentConversation(); setPage("tickets"); }}>Terminer</button>
              </div>
            </aside>
          </section>
        )}
      </main>
    </div>
  );
}

function TechnicianView({ technician = defaultTechnicianUser, onLogout }) {
  const [techPage, setTechPage] = useState("tickets");
  const [tab, setTab] = useState("tous");
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [tickets, setTickets] = useState([]);
  const [stats, setStats] = useState({ total: 0, critiques: 0, enCours: 0, resolus: 0 });
  const [reports, setReports] = useState(emptyReports);
  const [selectedId, setSelectedId] = useState("");
  const [closedIds, setClosedIds] = useState(new Set());
  const [localPriorities, setLocalPriorities] = useState({});
  const [takeoverOpen, setTakeoverOpen] = useState(false);
  const [takeoverText, setTakeoverText] = useState("");
  const [savingPriority, setSavingPriority] = useState(false);
  const [techChatInput, setTechChatInput] = useState("");
  const [techChatSending, setTechChatSending] = useState(false);
  const techChatBottomRef = useRef(null);

  useEffect(() => {
    loadTech();
    loadReports();
  }, []);

  // Réinitialise le champ de saisie quand on change de ticket
  useEffect(() => {
    setTechChatInput("");
    setTakeoverOpen(false);
    setTakeoverText("");
  }, [selectedId]);

  // Auto-scroll vers le bas de la conversation quand les messages changent
  useEffect(() => {
    techChatBottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [selectedId, tickets]);

  async function loadTech() {
    const data = await fetchTechnicianTickets();
    setTickets(data.tickets || []);
    setStats(data.stats || {});
    if (!selectedId && data.tickets?.length) setSelectedId(data.tickets[0].id);
  }

  async function loadReports() {
    const data = await fetchReportsSummary();
    setReports(data || emptyReports);
  }

  function parseNumericId(id) {
    return parseInt(String(id).replace(/\D/g, ""), 10);
  }

  async function handleSavePriority(ticketId) {
    const priority = localPriorities[ticketId];
    if (!priority) return;
    setSavingPriority(true);
    try {
      await updateTicketPriority({ ticket_id: parseNumericId(ticketId), priority });
      setLocalPriorities((prev) => { const next = { ...prev }; delete next[ticketId]; return next; });
      await loadTech();
    } catch (e) {
      alert(e.message);
    } finally {
      setSavingPriority(false);
    }
  }

  async function handleTakeover(ticketId) {
    try {
      await technicianTakeover({ ticket_id: parseNumericId(ticketId), response: takeoverText });
      setTakeoverOpen(false);
      setTakeoverText("");
      await loadTech();
    } catch (e) {
      alert(e.message);
    }
  }

  async function handleTechnicianMessage(ticketId) {
    const message = techChatInput.trim();
    if (!message || techChatSending) return;
    setTechChatSending(true);
    try {
      await technicianSendMessage(parseNumericId(ticketId), message);
      setTechChatInput("");
      await loadTech();
    } catch (e) {
      alert(e.message);
    } finally {
      setTechChatSending(false);
    }
  }

  const filtered = tickets.filter((ticket) => {
    const tabMatch = tab === "tous" || ticket.status === tab;
    const searchMatch = `${ticket.id} ${ticket.title} ${ticket.client} ${ticket.module} ${ticket.type}`.toLowerCase().includes(deferredSearch.toLowerCase());
    return tabMatch && searchMatch;
  });

  const selected = filtered.find((ticket) => ticket.id === selectedId) || tickets.find((ticket) => ticket.id === selectedId) || filtered[0];

  return (
    <div className="tech-shell">
      <header className="tech-topbar">
        <div className="brand-block">
          <div className="brand-badge">BIG</div>
          <div><strong>Console Technicien</strong><p>Supervision support ERP et interventions terrain</p></div>
        </div>
        <nav className="tech-nav">
          <button type="button" className={`tech-nav-link${techPage === "tickets" ? " active" : ""}`} onClick={() => setTechPage("tickets")}>Tickets</button>
          <button type="button" className={`tech-nav-link${techPage === "reports" ? " active" : ""}`} onClick={() => setTechPage("reports")}>Rapports</button>
        </nav>
        <div className="topbar-meta">
          <button type="button" className="topbar-logout tech" onClick={onLogout}>Deconnexion</button>
          <div className="user-card"><div className="user-avatar">{technician.initials}</div><div><strong>{technician.name}</strong><span>{technician.role}</span></div></div>
        </div>
      </header>

      <main className="tech-main">
        {techPage === "tickets" ? (
          <>
            <section className="hero-panel">
              <div className="hero-copy">
                <p className="section-kicker">Poste technicien</p>
                <h1>Priorise, diagnostique, resols.</h1>
                <p>Cette interface donne au technicien une vue immediate sur la file d'incidents, les suggestions IA, les tickets similaires et les actions de resolution.</p>
              </div>
              <div className="hero-stats">
                <MetricCard label="Tickets actifs" value={stats.total} tone="slate" />
                <MetricCard label="Critiques" value={stats.critiques} tone="red" />
                <MetricCard label="En cours" value={stats.enCours} tone="blue" />
                <MetricCard label="Resolus" value={stats.resolus} tone="green" />
              </div>
            </section>

            <section className="workspace-grid">
              <aside className="queue-panel">
                <div className="panel-head">
                  <div><p className="section-kicker">Queue</p><h2>Tickets a traiter</h2></div>
                </div>
                <div className="toolbar">
                  <input className="search-input" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Rechercher ticket, client, module..." />
                  <div className="tab-row">
                    {techTabs.map((item) => (
                      <button key={item.key} type="button" className={`tab-chip${tab === item.key ? " active" : ""}`} onClick={() => setTab(item.key)}>
                        {item.label}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="queue-list">
                  {filtered.map((ticket) => (
                    <button key={ticket.id} type="button" className={`queue-item${selected?.id === ticket.id ? " selected" : ""}`} onClick={() => setSelectedId(ticket.id)}>
                      <div className="queue-top"><strong>{ticket.id}</strong><span className={`badge ${ticket.priority}`}>{priorityLabel(ticket.priority)}</span></div>
                      <h3>{ticket.title}</h3>
                      <p>{ticket.client} | {ticket.site}</p>
                      <div className="queue-bottom">
                        <span>{ticket.module}</span>
                        <span>{ticket.type}</span>
                        <span className={`status-tag ${ticket.status}`}>{statusLabel(ticket.status)}</span>
                      </div>
                    </button>
                  ))}
                </div>
              </aside>

              <section className="detail-stack">
                {selected ? (
                  <>
                    <article className="detail-card main-detail">
                      <div className="detail-head">
                        <div><p className="section-kicker">Ticket selectionne</p><h2>{selected.title}</h2></div>
                        <div className="detail-head-right">
                          <div className="priority-inline">
                            <select
                              className="priority-select-inline"
                              value={localPriorities[selected.id] || selected.priority}
                              onChange={(e) => setLocalPriorities((prev) => ({ ...prev, [selected.id]: e.target.value }))}
                            >
                              <option value="normale">Faible</option>
                              <option value="moyenne">Moyenne</option>
                              <option value="haute">Haute</option>
                              <option value="critique">Critique</option>
                            </select>
                            {localPriorities[selected.id] && localPriorities[selected.id] !== selected.priority && (
                              <button
                                type="button"
                                className="save-priority-btn"
                                disabled={savingPriority}
                                onClick={() => handleSavePriority(selected.id)}
                              >
                                {savingPriority ? "..." : "Enregistrer"}
                              </button>
                            )}
                          </div>
                        </div>
                      </div>
                      <div className="detail-meta-grid">
                        <Info label="Client" value={selected.client} />
                        <Info label="Demandeur" value={selected.requester} />
                        <Info label="Module" value={selected.module} />
                        <Info label="Type" value={selected.type} />
                        <Info label="Ouvert a" value={selected.openedAt} />
                        <Info label="Derniere action" value={selected.lastAction} />
                      </div>
                      <div className="summary-box"><strong>Resume incident</strong><p>{selected.summary}</p></div>

                      {/* ── Chat conversation (toujours visible si ticket assigné) ── */}
                      {selected.status === "en_cours" ? (
                        <div className="tech-chat-panel">
                          <div className="tech-chat-header">
                            <strong>Discussion avec le client</strong>
                            <span className="tech-chat-live-dot" />
                          </div>
                          <div className="tech-chat-messages">
                            {selected.conversation && selected.conversation.length > 0 ? (
                              selected.conversation.map((msg, idx) => (
                                <div key={idx} className={`tech-chat-bubble ${msg.role}`}>
                                  <div className="tech-chat-bubble-meta">
                                    <span className="tech-chat-author">{msg.author}</span>
                                  </div>
                                  <p className="tech-chat-text">{msg.text}</p>
                                </div>
                              ))
                            ) : (
                              <div className="tech-chat-empty">
                                <p>Aucun message encore. Démarrez la discussion avec le client.</p>
                              </div>
                            )}
                            <div ref={techChatBottomRef} />
                          </div>
                          <div className="tech-chat-input-area">
                            <input
                              type="text"
                              className="tech-chat-input"
                              value={techChatInput}
                              onChange={(e) => setTechChatInput(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter" && !e.shiftKey) {
                                  e.preventDefault();
                                  handleTechnicianMessage(selected.id);
                                }
                              }}
                              placeholder="Écrire un message au client..."
                              disabled={techChatSending}
                            />
                            <button
                              type="button"
                              className="tech-chat-send-btn"
                              onClick={() => handleTechnicianMessage(selected.id)}
                              disabled={!techChatInput.trim() || techChatSending}
                            >
                              {techChatSending ? (
                                <span>...</span>
                              ) : (
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                                  <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
                                </svg>
                              )}
                            </button>
                          </div>
                        </div>
                      ) : selected.conversation && selected.conversation.length > 0 ? (
                        <div className="tech-conversation">
                          <div className="tech-conv-head">
                            <strong>Echanges client / technicien</strong>
                          </div>
                          <div className="tech-conv-messages">
                            {selected.conversation.map((msg, idx) => (
                              <div key={idx} className={`tech-conv-bubble ${msg.role}`}>
                                <span className="tech-conv-author">{msg.author}</span>
                                <p>{msg.text}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}

                      {takeoverOpen && (
                        <div className="takeover-box">
                          <strong>Reponse au client</strong>
                          <textarea
                            className="takeover-textarea"
                            rows={4}
                            placeholder="Ecrivez votre reponse au client ici..."
                            value={takeoverText}
                            onChange={(e) => setTakeoverText(e.target.value)}
                          />
                          <div className="takeover-actions">
                            <button type="button" className="primary-action" onClick={() => handleTakeover(selected.id)}>
                              Confirmer la prise en charge
                            </button>
                            <button type="button" className="secondary-action" onClick={() => { setTakeoverOpen(false); setTakeoverText(""); }}>
                              Annuler
                            </button>
                          </div>
                        </div>
                      )}

                      <div className="action-row">
                        {!takeoverOpen && selected.status !== "resolu" && selected.status !== "en_cours" && (
                          <button type="button" className="primary-action" onClick={() => setTakeoverOpen(true)}>
                            Prendre en charge
                          </button>
                        )}
                      </div>
                    </article>
                    <div className="detail-columns">
                      <article className="detail-card">
                        <div className="small-head">
                          <div><p className="section-kicker">Assistant IA</p><h3>Diagnostic propose</h3></div>
                          <span className="confidence-pill">{Math.round((selected.aiConfidence || 0) * 100)}% confiance</span>
                        </div>
                        <ul className="bullet-list">{(selected.diagnostics || []).map((item) => <li key={item}>{item}</li>)}</ul>
                      </article>
                      <article className="detail-card">
                        <div className="small-head"><div><p className="section-kicker">Procedure</p><h3>Checklist intervention</h3></div></div>
                        <div className="check-list">
                          {(selected.checklist || []).map((item) => (
                            <label key={item.label} className={`check-item${item.done ? " done" : ""}`}>
                              <input type="checkbox" checked={item.done} readOnly />
                              <span>{item.label}</span>
                            </label>
                          ))}
                        </div>
                      </article>
                    </div>
                  </>
                ) : null}
              </section>
            </section>
          </>
        ) : (
          <section className="reports-shell">
            <article className="reports-header-card">
              <div><h1>Rapports et Statistiques</h1><p>Analysez les performances et les tendances de votre systeme de tickets</p></div>
              <button type="button" className="primary-action">Exporter PDF</button>
            </article>
            <article className="reports-filter-bar">
              <div className="report-filter-group"><span>Periode:</span><select className="field-select" defaultValue="30j"><option value="7j">7 derniers jours</option><option value="30j">30 derniers jours</option><option value="90j">90 derniers jours</option></select></div>
              <div className="report-filter-group"><span>Type:</span><select className="field-select" defaultValue="all"><option value="all">Tous les rapports</option><option value="support">Support</option><option value="performance">Performance</option></select></div>
            </article>
            <section className="reports-kpi-grid">
              <ReportCard title="Tickets resolus" value={reports.kpis.resolved.value} delta={reports.kpis.resolved.delta} tone="green" />
              <ReportCard title="Temps de resolution moyen" value={reports.kpis.avg_resolution.value} delta={reports.kpis.avg_resolution.delta} tone="blue" />
              <ReportCard title="Satisfaction client" value={reports.kpis.satisfaction.value} delta={reports.kpis.satisfaction.delta} tone="purple" />
              <ReportCard title="Tickets en attente" value={reports.kpis.waiting.value} delta={reports.kpis.waiting.delta} tone="yellow" />
            </section>
            <section className="reports-grid">
              <article className="detail-card">
                <div className="small-head"><div><p className="section-kicker">Evolution</p><h3>Tendances mensuelles</h3></div></div>
                <div className="trend-list">
                  {(reports.monthly_trends || []).map((item) => (
                    <div key={item.month} className="trend-item">
                      <div className="trend-head"><strong>{item.month}</strong><span>{item.value}</span></div>
                      <div className="bar-track"><div className="bar-fill blue" style={{ width: `${item.percent * 100}%` }} /></div>
                    </div>
                  ))}
                </div>
              </article>
              <article className="detail-card">
                <div className="small-head"><div><p className="section-kicker">Repartition</p><h3>Tickets par categorie</h3></div></div>
                <div className="trend-list">
                  {(reports.categories || []).map((item) => (
                    <div key={item.label} className="trend-item">
                      <div className="trend-head"><strong>{item.label}</strong><span>{item.value} ({Math.round(item.percent * 100)}%)</span></div>
                      <div className="bar-track"><div className={`bar-fill ${item.tone}`} style={{ width: `${item.percent * 100}%` }} /></div>
                    </div>
                  ))}
                </div>
              </article>
            </section>
          </section>
        )}
      </main>
    </div>
  );
}

function Field({ label, help, children, required = false, error = "" }) {
  return (
    <label className={`field-group${error ? " has-error" : ""}`}>
      <span>
        {label}
        {required ? <em className="field-required">*</em> : null}
      </span>
      {children}
      {error ? <small className="field-help error">{error}</small> : null}
      {help ? <small className="field-help">{help}</small> : null}
    </label>
  );
}

function MetricCard({ label, value, tone }) {
  return <article className={`metric-card ${tone}`}><span>{label}</span><strong>{value}</strong></article>;
}

function ClientStatCard({ label, value, tone, icon }) {
  return <article className={`client-stat-card ${tone}`}><div><span>{label}</span><strong>{value}</strong></div><div className="client-stat-icon">{icon}</div></article>;
}

function ReportCard({ title, value, delta, tone }) {
  return <article className={`report-card ${tone}`}><span>{title}</span><strong>{value}</strong><p>{delta}</p></article>;
}

function Info({ label, value }) {
  return <div className="info-chip"><span>{label}</span><strong>{value}</strong></div>;
}

function buildInitials(name) {
  return (name || "")
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() || "")
    .join("") || "C";
}

function priorityLabel(priority) {
  if (priority === "critique" || priority === "urgente") return "Critique";
  if (priority === "haute") return "Haute";
  if (priority === "moyenne") return "Moyenne";
  return "Faible";
}

function statusLabel(status) {
  if (status === "nouveau") return "Nouveau";
  if (status === "en_cours") return "En cours";
  if (status === "en_attente_client") return "Attente client";
  return "Resolu";
}

function clientStatusLabel(status) {
  if (status === "ouvert" || status === "en_attente") return "En attente";
  if (status === "attribue") return "Assigne";
  if (status === "resolu") return "Resolu";
  return "En attente";
}

function countClientTab(tabKey, stats) {
  if (tabKey === "tous") return stats.total || 0;
  if (tabKey === "en_attente") return (stats.enAttente || 0) + (stats.ouverts || 0);
  if (tabKey === "attribue") return stats.attribues || 0;
  if (tabKey === "resolu") return stats.resolus || 0;
  return 0;
}

function assistantSolutionLabel(state) {
  const statut = state?.statut || "";
  if (statut === "solution_proposee") return "Solution proposee";
  if (state?.ready_for_assignment) return "Pret pour affectation";
  if (statut === "qualification" || statut === "escalade_technique") return "Prochaine action";
  return "Aide du chatbot";
}

function MailOutline() {
  return <svg viewBox="0 0 64 64" aria-hidden="true"><rect x="8" y="16" width="48" height="32" rx="6" fill="none" stroke="currentColor" strokeWidth="4" /><path d="M12 20 32 35 52 20" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round" /></svg>;
}

function UserOutline() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 12a4 4 0 1 0-4-4 4 4 0 0 0 4 4Zm-7 8a7 7 0 0 1 14 0" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

function MailSmall() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="3" fill="none" stroke="currentColor" strokeWidth="1.8" /><path d="m5.5 7.5 6.5 5 6.5-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

function PhoneOutline() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15.8 14.6c-1.9 1.9-3.9-.1-5.5-1.6-1.5-1.5-3.5-3.5-1.6-5.5l1-1a2 2 0 0 0 .2-2.6L8.3 1.8a2 2 0 0 0-3 .1L3.6 3.6c-3 3 1 8.9 3 10.9s7.9 6 10.9 3l1.7-1.7a2 2 0 0 0 .1-3l-2.1-1.6a2 2 0 0 0-2.6.2Z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

function BuildingOutline() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="3" width="14" height="18" rx="2" fill="none" stroke="currentColor" strokeWidth="1.8" /><path d="M9 7h1m4 0h1M9 11h1m4 0h1M9 15h1m4 0h1M11 21v-3h2v3" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>;
}

function BadgeOutline() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2" fill="none" stroke="currentColor" strokeWidth="1.8" /><path d="M8 10h8M8 14h4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /><circle cx="7.5" cy="12" r="1.2" fill="currentColor" /></svg>;
}

function LockOutline() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="10" width="16" height="10" rx="2" fill="none" stroke="currentColor" strokeWidth="1.8" /><path d="M8 10V7a4 4 0 0 1 8 0v3" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>;
}

function ArrowRightIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-5-5 5 5-5 5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

function WrenchIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14.5 6.5 3-3a3 3 0 0 1 3 3l-3 3-9.5 9.5a2.1 2.1 0 0 1-3 0 2.1 2.1 0 0 1 0-3Z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /><path d="m13 8 3 3" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>;
}

function CalendarOutline() {
  return <svg viewBox="0 0 64 64" aria-hidden="true"><rect x="12" y="16" width="40" height="36" rx="6" fill="none" stroke="currentColor" strokeWidth="4" /><path d="M12 26h40M22 10v12M42 10v12" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round" /></svg>;
}

function CheckOutline() {
  return <svg viewBox="0 0 64 64" aria-hidden="true"><path d="m16 34 10 10 22-26" fill="none" stroke="currentColor" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}
