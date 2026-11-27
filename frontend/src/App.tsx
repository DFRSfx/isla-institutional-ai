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
  const [animatingMessageId, setAnimatingMessageId] = useState<string | null>(null);
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null);
  const [liveStageLabel, setLiveStageLabel] = useState<string | null>(null);
  const [liveStages, setLiveStages] = useState<string[]>([]);
  const [liveThinking, setLiveThinking] = useState("");
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
    setAnimatingMessageId(null);
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
    setAnimatingMessageId(null);
    setMessages([]);
    setChatError(null);
  };

  const handleDeleteConversation = async (id: string) => {
    try {
      await api.deleteConversation(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (activeConversationId === id) {
        setActiveConversationId(null);
        setAnimatingMessageId(null);
        setMessages([]);
        setChatError(null);
      }
    } catch (err) {
      setChatError(err instanceof ApiError ? err.message : "Erro ao eliminar conversação.");
    }
  };

  const handleSendMessage = async (text: string) => {
    setChatError(null);
    setLiveStageLabel(null);
    setLiveStages([]);
    setLiveThinking("");
    const optimisticUserMsg: MessageItem = {
      id: `temp-${Date.now()}`,
      role: "user",
      content: text,
      sources_json: [],
      tool_calls_json: [],
      created_at: new Date().toISOString(),
    };
    const streamTempId = `stream-${Date.now()}`;
    let streamCreated = false;

    const ensureStreamMessage = (patch: Partial<MessageItem> = {}) => {
      if (!streamCreated) {
        streamCreated = true;
        setStreamingMessageId(streamTempId);
        const initial: MessageItem = {
          id: streamTempId,
          role: "assistant",
          content: "",
          sources_json: [],
          tool_calls_json: [],
          created_at: new Date().toISOString(),
          ...patch,
        };
        setMessages((prev) => [...prev, initial]);
      } else if (Object.keys(patch).length > 0) {
        setMessages((prev) =>
          prev.map((m) => (m.id === streamTempId ? { ...m, ...patch } : m)),
        );
      }
    };

    setMessages((prev) => [...prev, optimisticUserMsg]);
    setIsSending(true);
    try {
      await api.sendChatMessageStream(text, activeConversationId, {
        onStage: (stage) => {
          setLiveStageLabel(stage.label);
          setLiveStages((prev) =>
            prev[prev.length - 1] === stage.label ? prev : [...prev, stage.label],
          );
        },
        onThought: (thought) => {
          if (!thought.text) return;
          setLiveThinking((prev) => prev + thought.text);
        },
        onMeta: (meta) => {
          setActiveConversationId(meta.conversation_id);
          if (meta.plan && meta.plan.length > 0) {
            setLiveStages((prev) => [...prev, ...meta.plan]);
          }
          ensureStreamMessage({
            plan: meta.plan,
            tool_calls_json: meta.tool_calls,
            sources_json: meta.sources,
            report_bundle: meta.report_bundle,
            analytics_summary: meta.analytics_summary,
          });
        },
        onDelta: (delta) => {
          if (!delta.text) return;
          if (!streamCreated) {
            ensureStreamMessage({ content: delta.text });
          } else {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === streamTempId ? { ...m, content: m.content + delta.text } : m,
              ),
            );
          }
        },
        onDone: (done) => {
          setActiveConversationId(done.conversation_id);
          setStreamingMessageId(null);
          setLiveStageLabel(null);
          setLiveStages([]);
          setLiveThinking("");
          setMessages((prev) =>
            prev.map((m) =>
              m.id === streamTempId
                ? {
                    ...m,
                    id: done.message_id,
                    content: done.answer,
                    needs_clarification: done.needs_clarification,
                    elapsed_seconds: done.elapsed_seconds,
                    thinking_text: done.thinking_text ?? null,
                  }
                : m,
            ),
          );
        },
      });
      void loadConversations();
    } catch (err) {
      setStreamingMessageId(null);
      setLiveStageLabel(null);
      setChatError(err instanceof ApiError ? err.message : "Erro ao comunicar com o agente.");
    } finally {
      setIsSending(false);
    }
  };

  const handleTypingComplete = useCallback(() => {
    setAnimatingMessageId(null);
  }, []);

  const handleLogout = async () => {
    try {
      await api.logout();
    } catch {
      // limpa estado local mesmo se a sessão já tiver expirado
    }
    setUser(null);
    setConversations([]);
    setMessages([]);
    setAnimatingMessageId(null);
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
        onDeleteConversation={(id) => void handleDeleteConversation(id)}
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
            animatingMessageId={animatingMessageId}
            streamingMessageId={streamingMessageId}
            liveStageLabel={liveStageLabel}
            liveStages={liveStages}
            liveThinking={liveThinking}
            onTypingComplete={handleTypingComplete}
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
