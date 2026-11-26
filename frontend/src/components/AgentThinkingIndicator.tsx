import { useEffect, useState } from "react";
import {
  BarChart3,
  Check,
  Database,
  FileCheck2,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

interface ThinkingStage {
  label: string;
  detail: string;
  thresholdMs: number;
  icon: typeof Sparkles;
}

const THINKING_STAGES: ThinkingStage[] = [
  {
    label: "A interpretar a pergunta e verificar permissões...",
    detail: "Validação RBAC e contexto conversacional",
    thresholdMs: 0,
    icon: ShieldCheck,
  },
  {
    label: "A consultar fontes estruturadas do ISLA...",
    detail: "Portal Científico e base de investigadores",
    thresholdMs: 2200,
    icon: Database,
  },
  {
    label: "A cruzar autores e validar cálculos em SQL...",
    detail: "Agregação determinística e indicadores KPI",
    thresholdMs: 5500,
    icon: BarChart3,
  },
  {
    label: "A redigir resposta com o modelo local ISLA...",
    detail: "Síntese analítica em processamento local (RGPD)",
    thresholdMs: 10500,
    icon: Sparkles,
  },
  {
    label: "A consolidar fontes e rastreabilidade...",
    detail: "Verificação de proveniência e formatação final",
    thresholdMs: 22000,
    icon: FileCheck2,
  },
];

interface AgentThinkingIndicatorProps {
  liveStageLabel?: string | null;
}

export function AgentThinkingIndicator({ liveStageLabel }: AgentThinkingIndicatorProps = {}) {
  const [elapsedMs, setElapsedMs] = useState(0);

  useEffect(() => {
    const startedAt = performance.now();
    const timer = window.setInterval(() => {
      setElapsedMs(performance.now() - startedAt);
    }, 150);
    return () => window.clearInterval(timer);
  }, []);

  let activeIdx = 0;
  for (let i = 0; i < THINKING_STAGES.length; i++) {
    if (elapsedMs >= THINKING_STAGES[i].thresholdMs) {
      activeIdx = i;
    }
  }

  const activeStage = THINKING_STAGES[activeIdx];
  const ActiveIcon = activeStage.icon;
  const displayLabel = liveStageLabel || activeStage.label;
  const elapsedSeconds = (elapsedMs / 1000).toFixed(1);

  return (
    <div
      className="flex items-start gap-3 animate-chat-msg-enter"
      role="status"
      aria-live="polite"
      aria-label={displayLabel}
    >
      {/* Avatar animado com aura subtil */}
      <div className="relative h-7 w-7 shrink-0 mt-0.5">
        <span
          aria-hidden="true"
          className="absolute inset-0 rounded-lg bg-emerald-500/25 blur-[5px] animate-chat-aura"
        />
        <div className="relative h-7 w-7 rounded-lg bg-neutral-900 border border-emerald-500/40 flex items-center justify-center">
          <Sparkles className="w-3.5 h-3.5 text-emerald-400" />
        </div>
      </div>

      {/* Cartão de progresso conversacional */}
      <div className="flex-1 min-w-0 max-w-xl rounded-2xl bg-neutral-900/75 border border-neutral-800/90 px-4 py-3 space-y-3 shadow-sm">
        {/* Cabeçalho com shimmer + typing dots + cronómetro */}
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 min-w-0">
            <ActiveIcon className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
            <span
              key={displayLabel}
              className="text-xs font-medium truncate animate-chat-shimmer-text animate-chat-step-enter"
            >
              {displayLabel}
            </span>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <span className="inline-flex items-center gap-1" aria-hidden="true">
              <span
                className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-chat-dot"
                style={{ animationDelay: "0ms" }}
              />
              <span
                className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-chat-dot"
                style={{ animationDelay: "180ms" }}
              />
              <span
                className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-chat-dot"
                style={{ animationDelay: "360ms" }}
              />
            </span>
            <span className="text-[11px] font-mono tabular-nums text-neutral-500">
              {elapsedSeconds}s
            </span>
          </div>
        </div>

        {/* Etapas percorridas até ao momento */}
        <div className="space-y-1.5 border-l border-neutral-800 pl-3 ml-1.5">
          {THINKING_STAGES.slice(0, activeIdx + 1).map((stage, idx) => {
            const isDone = idx < activeIdx;
            return (
              <div
                key={stage.label}
                className="flex items-center gap-2 text-[11px] animate-chat-step-enter"
              >
                {isDone ? (
                  <span className="h-3.5 w-3.5 rounded-full bg-emerald-500/15 border border-emerald-500/40 flex items-center justify-center shrink-0">
                    <Check className="w-2.5 h-2.5 text-emerald-400" />
                  </span>
                ) : (
                  <span className="h-3.5 w-3.5 rounded-full border border-emerald-400/60 flex items-center justify-center shrink-0">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  </span>
                )}
                <span className={isDone ? "text-neutral-500" : "text-neutral-300"}>
                  {stage.detail}
                </span>
              </div>
            );
          })}
        </div>

        {/* Linhas skeleton subtis a simular composição da resposta */}
        <div className="space-y-1.5 pt-0.5" aria-hidden="true">
          <div className="h-2 w-11/12 rounded-full animate-chat-skeleton" />
          <div
            className="h-2 w-4/5 rounded-full animate-chat-skeleton"
            style={{ animationDelay: "220ms" }}
          />
          <div
            className="h-2 w-3/5 rounded-full animate-chat-skeleton"
            style={{ animationDelay: "440ms" }}
          />
        </div>
      </div>
    </div>
  );
}
