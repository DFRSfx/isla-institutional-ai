import {
  Database,
  LogOut,
  MessageSquare,
  Plus,
  ShieldAlert,
  Sparkles,
  X,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { ConversationItem, UserProfile } from "@/types/api";

export type ActiveSection = "chat" | "admin" | "audit";

const ROLE_LABELS: Record<string, string> = {
  admin: "Administrador",
  direction: "Direção",
  faculty: "Docente",
};

interface SidebarProps {
  user: UserProfile;
  activeSection: ActiveSection;
  onSelectSection: (section: ActiveSection) => void;
  conversations: ConversationItem[];
  activeConversationId: string | null;
  onSelectConversation: (id: string) => void;
  onNewConversation: () => void;
  onLogout: () => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}

export function Sidebar({
  user,
  activeSection,
  onSelectSection,
  conversations,
  activeConversationId,
  onSelectConversation,
  onNewConversation,
  onLogout,
  mobileOpen,
  onCloseMobile,
}: SidebarProps) {
  const canAccessAdmin = user.role === "admin" || user.role === "direction";
  const canViewAudit = user.permissions.includes("view_audit_logs");

  const content = (
    <aside className="flex flex-col h-full w-64 bg-neutral-950 border-r border-neutral-800/80 select-none">
      <div className="flex items-center justify-between px-4 h-14 border-b border-neutral-800/70">
        <div className="flex items-center gap-2.5">
          <div className="h-7 w-7 rounded-lg bg-white text-black flex items-center justify-center">
            <Sparkles className="w-4 h-4" />
          </div>
          <div className="leading-tight">
            <div className="text-sm font-semibold text-white tracking-tight">ISLA AI</div>
            <div className="text-[10px] font-mono text-neutral-500">MVP v1.0</div>
          </div>
        </div>
        <button
          type="button"
          onClick={onCloseMobile}
          className="lg:hidden p-1.5 text-neutral-400 hover:text-white rounded-md"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="p-3 space-y-1.5">
        <button
          type="button"
          onClick={() => {
            onSelectSection("chat");
            onNewConversation();
            onCloseMobile();
          }}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 text-xs font-medium text-white transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          Nova conversa
        </button>

        <nav className="pt-2 space-y-0.5">
          <button
            type="button"
            onClick={() => {
              onSelectSection("chat");
              onCloseMobile();
            }}
            className={cn(
              "w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors",
              activeSection === "chat"
                ? "bg-neutral-800/90 text-white"
                : "text-neutral-400 hover:text-white hover:bg-neutral-900"
            )}
          >
            <MessageSquare className="w-3.5 h-3.5" />
            Assistente IA
          </button>

          {canAccessAdmin && (
            <button
              type="button"
              onClick={() => {
                onSelectSection("admin");
                onCloseMobile();
              }}
              className={cn(
                "w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors",
                activeSection === "admin"
                  ? "bg-neutral-800/90 text-white"
                  : "text-neutral-400 hover:text-white hover:bg-neutral-900"
              )}
            >
              <Database className="w-3.5 h-3.5" />
              Fontes & Excel
            </button>
          )}

          {canViewAudit && (
            <button
              type="button"
              onClick={() => {
                onSelectSection("audit");
                onCloseMobile();
              }}
              className={cn(
                "w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors",
                activeSection === "audit"
                  ? "bg-neutral-800/90 text-white"
                  : "text-neutral-400 hover:text-white hover:bg-neutral-900"
              )}
            >
              <ShieldAlert className="w-3.5 h-3.5" />
              Auditoria
            </button>
          )}
        </nav>
      </div>

      <div className="px-4 pt-3 pb-1.5 text-[10px] font-mono uppercase tracking-wider text-neutral-500">
        Histórico
      </div>
      <div className="flex-1 overflow-y-auto px-2 pb-3 space-y-0.5">
        {conversations.length === 0 ? (
          <p className="px-2 py-3 text-xs text-neutral-600">Sem conversações anteriores.</p>
        ) : (
          conversations.map((conv) => (
            <button
              key={conv.id}
              type="button"
              onClick={() => {
                onSelectSection("chat");
                onSelectConversation(conv.id);
                onCloseMobile();
              }}
              className={cn(
                "w-full text-left px-2.5 py-2 rounded-lg text-xs truncate transition-colors",
                activeSection === "chat" && activeConversationId === conv.id
                  ? "bg-neutral-900 text-white border border-neutral-800"
                  : "text-neutral-400 hover:text-neutral-100 hover:bg-neutral-900/60"
              )}
              title={conv.title}
            >
              {conv.title}
            </button>
          ))
        )}
      </div>

      <div className="p-3 border-t border-neutral-800/80 flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="text-xs font-medium text-neutral-200 truncate">{user.full_name}</div>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            <span className="text-[11px] font-mono text-neutral-400 truncate">
              {ROLE_LABELS[user.role] ?? user.role}
            </span>
          </div>
        </div>
        <button
          type="button"
          onClick={onLogout}
          title="Terminar sessão"
          className="p-2 rounded-lg text-neutral-400 hover:text-white hover:bg-neutral-900 transition-colors"
        >
          <LogOut className="w-4 h-4" />
        </button>
      </div>
    </aside>
  );

  return (
    <>
      <div className="hidden lg:block h-screen sticky top-0">{content}</div>
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden flex">
          <div className="fixed inset-0 bg-black/70" onClick={onCloseMobile} />
          <div className="relative z-10 h-full">{content}</div>
        </div>
      )}
    </>
  );
}
