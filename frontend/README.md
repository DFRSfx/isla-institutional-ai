# Frontend — ISLA Institutional AI Agent

Aplicação **React + TypeScript + Tailwind CSS** com estrutura **shadcn** (`@/components/ui`, `@/lib/utils.ts`, `components.json`), baseada no padrão `v0-ai-chat` / Vercel AI Chatbot.

## Estrutura

- `src/components/ui/textarea.tsx`: primitiva `Textarea` (shadcn)
- `src/components/ui/v0-ai-chat.tsx`: *composer* auto-ajustável (`VercelV0Chat`) com ações rápidas institucionais e atalho de importação Excel para administradores
- `src/components/Sidebar.tsx`: barra lateral com histórico de conversações e navegação RBAC
- `src/components/ChatMessageCard.tsx`: renderização de respostas fundamentadas, KPIs, gráfico anual, downloads autenticados PDF/Excel e painel de rastreabilidade de fontes
- `src/pages/LoginPage.tsx`: autenticação JWT (`POST /api/v1/auth/login`)
- `src/pages/ChatPage.tsx`: conversação em linguagem natural com memória contextual
- `src/pages/AdminPage.tsx`: sincronização do Portal Científico, pré-visualização/importação de Excel e registo de auditoria

## Arranque em desenvolvimento

```bash
cd frontend
npm install
npm run dev
```

O servidor Vite arranca em `http://localhost:5173` com *proxy* automático de `/api` para o backend FastAPI em `http://127.0.0.1:8000`.
