import { useEffect, useRef } from "react";

import { AgentThinkingIndicator } from "@/components/AgentThinkingIndicator";
import { ChatMessageCard } from "@/components/ChatMessageCard";
import { VercelV0Chat } from "@/components/ui/v0-ai-chat";
import type { MessageItem, UserProfile } from "@/types/api";

interface ChatPageProps {
  user: UserProfile;
  messages: MessageItem[];
  isSending: boolean;
  error: string | null;
  onSendMessage: (message: string) => Promise<void>;
  onNewConversation: () => void;
  onOpenExcelImport: () => void;
}

export function ChatPage({
  user,
  messages,
  isSending,
  error,
  onSendMessage,
  onNewConversation,
  onOpenExcelImport,
}: ChatPageProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const canUploadExcel = user.permissions.includes("import_excel");

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, isSending]);

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center min-h-[calc(100vh-3.5rem)]">
        {error && (
          <div className="mb-4 max-w-xl rounded-lg border border-red-900/60 bg-red-950/50 px-4 py-2 text-xs text-red-200">
            {error}
          </div>
        )}
        <VercelV0Chat
          onSend={onSendMessage}
          onNewChat={onNewConversation}
          onOpenExcelImport={onOpenExcelImport}
          canUploadExcel={canUploadExcel}
          isLoading={isSending}
          userRole={user.role}
        />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col h-[calc(100vh-3.5rem)] lg:h-screen">
      <div className="flex-1 overflow-y-auto px-4 py-6">
        <div className="max-w-3xl mx-auto space-y-6">
          {messages.map((msg) => (
            <ChatMessageCard key={msg.id} message={msg} />
          ))}
          {isSending && <AgentThinkingIndicator />}
          {error && (
            <div className="rounded-lg border border-red-900/60 bg-red-950/50 px-4 py-2.5 text-xs text-red-200">
              {error}
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="border-t border-neutral-800/80 bg-neutral-950/95 backdrop-blur">
        <VercelV0Chat
          compact
          onSend={onSendMessage}
          onNewChat={onNewConversation}
          onOpenExcelImport={onOpenExcelImport}
          canUploadExcel={canUploadExcel}
          isLoading={isSending}
          userRole={user.role}
          placeholder="Pede esclarecimentos ou refina o relatório (ex.: Acrescenta uma comparação entre 2024 e 2025)..."
        />
      </div>
    </div>
  );
}
