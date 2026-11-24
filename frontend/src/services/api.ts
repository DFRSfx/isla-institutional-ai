import type {
  AuditLogItem,
  ChatResponse,
  ConversationItem,
  ExcelImportRecord,
  ExcelPreviewResponse,
  MessageItem,
  PendingAuthorMatch,
  SourceSnapshot,
  TokenResponse,
  UserProfile,
} from "@/types/api";

const TOKEN_STORAGE_KEY = "isla_ai_access_token";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// Armazenamento em sessionStorage (limpo ao fechar o separador/sessão).
// Antes de produção, migrar para cookie HttpOnly; Secure; SameSite=Lax emitido pelo backend.
export function getStoredToken(): string | null {
  return sessionStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setStoredToken(token: string | null): void {
  if (token) {
    sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
  } else {
    sessionStorage.removeItem(TOKEN_STORAGE_KEY);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getStoredToken();
  const headers = new Headers(init.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (!(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let detail = `Erro HTTP ${res.status}`;
    try {
      const payload = (await res.json()) as { detail?: string };
      if (payload.detail) detail = payload.detail;
    } catch {
      // ignora payload não-JSON
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const api = {
  login(username: string, password: string): Promise<TokenResponse> {
    return request<TokenResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
  },

  me(): Promise<UserProfile> {
    return request<UserProfile>("/api/v1/auth/me");
  },

  sendChatMessage(message: string, conversationId?: string | null): Promise<ChatResponse> {
    return request<ChatResponse>("/api/v1/chat", {
      method: "POST",
      body: JSON.stringify({
        message,
        conversation_id: conversationId ?? null,
      }),
    });
  },

  listConversations(): Promise<ConversationItem[]> {
    return request<ConversationItem[]>("/api/v1/conversations");
  },

  listMessages(conversationId: string): Promise<MessageItem[]> {
    return request<MessageItem[]>(`/api/v1/conversations/${conversationId}/messages`);
  },

  async downloadReport(url: string, fallbackFilename: string): Promise<void> {
    const token = getStoredToken();
    const res = await fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) {
      throw new ApiError(res.status, "Não foi possível descarregar o relatório.");
    }
    const blob = await res.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = fallbackFilename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
  },

  syncPortal(nocache = false): Promise<SourceSnapshot> {
    return request<SourceSnapshot>("/api/v1/sync/portal", {
      method: "POST",
      body: JSON.stringify({ nocache }),
    });
  },

  listSnapshots(): Promise<SourceSnapshot[]> {
    return request<SourceSnapshot[]>("/api/v1/sync/snapshots?limit=20");
  },

  previewExcel(file: File, sheetName?: string): Promise<ExcelPreviewResponse> {
    const form = new FormData();
    form.append("file", file);
    const query = sheetName ? `?sheet_name=${encodeURIComponent(sheetName)}` : "";
    return request<ExcelPreviewResponse>(`/api/v1/imports/excel/preview${query}`, {
      method: "POST",
      body: form,
    });
  },

  importExcel(file: File, sheetName?: string): Promise<ExcelImportRecord> {
    const form = new FormData();
    form.append("file", file);
    const query = sheetName ? `?sheet_name=${encodeURIComponent(sheetName)}` : "";
    return request<ExcelImportRecord>(`/api/v1/imports/excel${query}`, {
      method: "POST",
      body: form,
    });
  },

  listExcelImports(): Promise<ExcelImportRecord[]> {
    return request<ExcelImportRecord[]>("/api/v1/imports/excel?limit=20");
  },

  listAuditLogs(): Promise<AuditLogItem[]> {
    return request<AuditLogItem[]>("/api/v1/audit/logs?limit=100");
  },

  listUsers(): Promise<UserProfile[]> {
    return request<UserProfile[]>("/api/v1/users");
  },

  createUser(payload: {
    email: string;
    full_name: string;
    password: string;
    role: string;
  }): Promise<UserProfile> {
    return request<UserProfile>("/api/v1/users", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  updateUser(
    userId: string,
    payload: { role?: string; is_active?: boolean }
  ): Promise<UserProfile> {
    return request<UserProfile>(`/api/v1/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },

  listPendingAuthorMatches(): Promise<PendingAuthorMatch[]> {
    return request<PendingAuthorMatch[]>("/api/v1/review/author-matches");
  },

  decideAuthorMatch(
    authorshipId: string,
    action: "approve" | "reject",
    researcherId?: string | null
  ): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>(`/api/v1/review/author-matches/${authorshipId}`, {
      method: "POST",
      body: JSON.stringify({ action, researcher_id: researcherId ?? null }),
    });
  },
};
