import { useCallback, useEffect, useState } from "react";
import { Menu } from "lucide-react";

import { type ActiveSection, Sidebar } from "@/components/Sidebar";
import { AdminPage } from "@/pages/AdminPage";
import { ChatPage } from "@/pages/ChatPage";
import { LoginPage } from "@/pages/LoginPage";
import { ReportsPage } from "@/pages/ReportsPage";
import { ApiError, api } from "@/services/api";
import type { ConversationItem, MessageItem, UserProfile } from "@/types/api";

export function App() {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [bootstrapping, setBootstrapping] = useState(true);
  const [activeSection, setActiveSection] = useState<ActiveSection>("chat");
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);

  const loadConversations = useCallback(async () => {
    try {
      const list = await api.listConversations();
      setConversations(list);
    } catch {
      // ignora erro transitório na listagem
    }
  }, []);

  useEffect(() => {
    api
      .me()
      .then((profile) => {
        setUser(profile);
        return loadConversations();
      })
      .catch(() => {
        setUser(null);
      })
      .finally(() => setBootstrapping(false));
  }, [loadConversations]);

  const handleSelectConversation = async (id: string) => {
    setActiveConversationId(id);
    setChatError(null);
    try {
      const history = await api.listMessages(id);
      setMessages(history);
    } catch (err) {
      setChatError(err instanceof ApiError ? err.message : "Erro ao carregar conversação.");
    }
  };

  const handleNewConversation = () => {
    setActiveConversationId(null);
    setMessages([]);
    setChatError(null);
  };

  const handleSendMessage = async (text: string) => {
    setChatError(null);
    const optimisticUserMsg: MessageItem = {
      id: `temp-${Date.now()}`,
      role: "user",
      content: text,
      sources_json: [],
      tool_calls_json: [],
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimisticUserMsg]);
    setIsSending(true);
    try {
      const res = await api.sendChatMessage(text, activeConversationId);
      setActiveConversationId(res.conversation_id);
      const assistantMsg: MessageItem = {
        id: res.message_id,
        role: "assistant",
        content: res.answer,
        sources_json: res.sources,
        tool_calls_json: res.tool_calls,
        created_at: new Date().toISOString(),
        plan: res.plan,
        report_bundle: res.report_bundle,
        analytics_summary: res.analytics_summary,
        needs_clarification: res.needs_clarification,
      };
      setMessages((prev) => [...prev, assistantMsg]);
      void loadConversations();
    } catch (err) {
      setChatError(err instanceof ApiError ? err.message : "Erro ao comunicar com o agente.");
    } finally {
      setIsSending(false);
    }
  };

  const handleLogout = async () => {
    try {
      await api.logout();
    } catch {
      // limpa estado local mesmo se a sessão já tiver expirado
    }
    setUser(null);
    setConversations([]);
    setMessages([]);
    setActiveConversationId(null);
  };

  if (bootstrapping) {
    return (
      <div className="min-h-screen bg-neutral-950 flex items-center justify-center text-xs font-mono text-neutral-500">
        A inicializar sessão...
      </div>
    );
  }

  if (!user) {
    return (
      <LoginPage
        onAuthenticated={(profile) => {
          setUser(profile);
          void loadConversations();
        }}
      />
    );
  }

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100 flex">
      <Sidebar
        user={user}
        activeSection={activeSection}
        onSelectSection={setActiveSection}
        conversations={conversations}
        activeConversationId={activeConversationId}
        onSelectConversation={(id) => void handleSelectConversation(id)}
        onNewConversation={handleNewConversation}
        onLogout={() => void handleLogout()}
        mobileOpen={mobileOpen}
        onCloseMobile={() => setMobileOpen(false)}
      />

      <div className="flex-1 flex flex-col min-w-0">
        <header className="lg:hidden h-14 px-4 border-b border-neutral-800/80 flex items-center justify-between">
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            className="p-2 -ml-2 text-neutral-300 hover:text-white"
          >
            <Menu className="w-5 h-5" />
          </button>
          <span className="text-sm font-semibold text-white">ISLA Institutional AI</span>
          <div className="w-8" />
        </header>

        {activeSection === "chat" && (
          <ChatPage
            user={user}
            messages={messages}
            isSending={isSending}
            error={chatError}
            onSendMessage={handleSendMessage}
            onNewConversation={handleNewConversation}
            onOpenExcelImport={() => setActiveSection("admin")}
          />
        )}

        {activeSection === "reports" && <ReportsPage />}

        {(activeSection === "admin" || activeSection === "audit") && (
          <AdminPage user={user} mode={activeSection} />
        )}
      </div>
    </div>
  );
}

export default App;
