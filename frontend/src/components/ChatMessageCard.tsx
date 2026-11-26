import { useEffect, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Database,
  FileSpreadsheet,
  FileText,
  HelpCircle,
  Sparkles,
} from "lucide-react";

import { api } from "@/services/api";
import type { MessageItem } from "@/types/api";

interface ChatMessageCardProps {
  message: MessageItem;
  animateTyping?: boolean;
  onTypingComplete?: () => void;
}

function renderFormattedLines(content: string, showCursor = false) {
  const lines = content.split("\n");
  let lastNonEmptyIdx = lines.length - 1;
  while (lastNonEmptyIdx > 0 && !lines[lastNonEmptyIdx].trim()) {
    lastNonEmptyIdx--;
  }

  const cursorEl = showCursor ? (
    <span
      aria-hidden="true"
      className="inline-block w-[7px] h-[14px] align-middle ml-1 rounded-[2px] bg-emerald-400/90 animate-chat-cursor"
    />
  ) : null;

  return lines.map((line, idx) => {
    const trimmed = line.trim();
    const isCursorLine = showCursor && idx === lastNonEmptyIdx;
    if (!trimmed) {
      if (isCursorLine) {
        return (
          <p key={idx} className="text-sm text-neutral-300 leading-relaxed">
            {cursorEl}
          </p>
        );
      }
      return <div key={idx} className="h-2" />;
    }
    if (trimmed.startsWith("### ")) {
      return (
        <h3 key={idx} className="text-base font-semibold text-white tracking-tight pt-1">
          {trimmed.slice(4)}
          {isCursorLine && cursorEl}
        </h3>
      );
    }
    const isBullet = trimmed.startsWith("- ");
    const cleanText = isBullet ? trimmed.slice(2) : trimmed;

    // Renderização simples e segura de **negrito** e `código`
    const parts = cleanText.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
    const rendered = parts.map((part, pIdx) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return (
          <strong key={pIdx} className="font-semibold text-white">
            {part.slice(2, -2)}
          </strong>
        );
      }
      if (part.startsWith("`") && part.endsWith("`")) {
        return (
          <code
            key={pIdx}
            className="px-1.5 py-0.5 rounded bg-neutral-800 text-emerald-300 font-mono text-[11px]"
          >
            {part.slice(1, -1)}
          </code>
        );
      }
      return <span key={pIdx}>{part}</span>;
    });

    if (isBullet) {
      return (
        <div key={idx} className="flex gap-2 text-sm text-neutral-300 leading-relaxed pl-1">
          <span className="text-neutral-500 select-none">•</span>
          <span>
            {rendered}
            {isCursorLine && cursorEl}
          </span>
        </div>
      );
    }
    return (
      <p key={idx} className="text-sm text-neutral-300 leading-relaxed">
        {rendered}
        {isCursorLine && cursorEl}
      </p>
    );
  });
}

export function ChatMessageCard({
  message,
  animateTyping = false,
  onTypingComplete,
}: ChatMessageCardProps) {
  const [showProvenance, setShowProvenance] = useState(false);
  const [downloading, setDownloading] = useState<"pdf" | "excel" | null>(null);
  const [revealedChars, setRevealedChars] = useState<number>(() =>
    animateTyping && message.role === "assistant" ? 0 : message.content.length,
  );

  useEffect(() => {
    if (!animateTyping || message.role !== "assistant") {
      setRevealedChars(message.content.length);
      return;
    }

    const prefersReducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReducedMotion || message.content.length === 0) {
      setRevealedChars(message.content.length);
      onTypingComplete?.();
      return;
    }

    const totalLen = message.content.length;
    // Duração adaptativa entre ~0.9s e ~3.4s para fluidez estilo ChatGPT/Claude
    const durationMs = Math.min(Math.max(totalLen * 4.5, 900), 3400);
    const startedAt = performance.now();
    let rafId = 0;

    const step = (now: number) => {
      const progress = Math.min((now - startedAt) / durationMs, 1);
      // Curva ligeiramente suavizada no final
      const eased = 1 - Math.pow(1 - progress, 1.35);
      let nextChars = Math.max(1, Math.floor(eased * totalLen));

      // Avança até ao fim da palavra atual quando próximo de espaço para evitar quebras bruscas
      if (nextChars < totalLen) {
        const nextSpace = message.content.indexOf(" ", nextChars);
        if (nextSpace !== -1 && nextSpace - nextChars <= 6) {
          nextChars = nextSpace + 1;
        }
      }

      setRevealedChars(nextChars);
      if (progress < 1) {
        rafId = window.requestAnimationFrame(step);
      } else {
        setRevealedChars(totalLen);
        onTypingComplete?.();
      }
    };

    rafId = window.requestAnimationFrame(step);
    return () => window.cancelAnimationFrame(rafId);
  }, [animateTyping, message.content, message.id, message.role, onTypingComplete]);

  const isTyping = animateTyping && message.role === "assistant" && revealedChars < message.content.length;
  const visibleContent = isTyping ? message.content.slice(0, revealedChars) : message.content;

  if (message.role === "user") {
    return (
      <div className="flex justify-end animate-chat-msg-enter">
        <div className="max-w-[82%] rounded-2xl bg-neutral-800/90 border border-neutral-700/70 px-4 py-2.5 text-sm text-white leading-relaxed">
          {message.content}
        </div>
      </div>
    );
  }

  const kpis = message.analytics_summary?.kpis;
  const annual = message.analytics_summary?.annual_evolution ?? [];
  const maxAnnual = Math.max(...annual.map((a) => a.publications), 1);

  const handleDownload = async (fmt: "pdf" | "excel") => {
    if (!message.report_bundle) return;
    setDownloading(fmt);
    try {
      const url = fmt === "pdf" ? message.report_bundle.pdf_url : message.report_bundle.excel_url;
      const ext = fmt === "pdf" ? "pdf" : "xlsx";
      await api.downloadReport(url, `isla_relatorio_${message.report_bundle.report_id}.${ext}`);
    } finally {
      setDownloading(null);
    }
  };

  return (
    <div className="flex items-start gap-3 animate-chat-msg-enter">
      <div className="h-7 w-7 rounded-lg bg-neutral-900 border border-neutral-800 flex items-center justify-center shrink-0 mt-0.5">
        {message.needs_clarification ? (
          <HelpCircle className="w-3.5 h-3.5 text-amber-400" />
        ) : (
          <Sparkles className="w-3.5 h-3.5 text-emerald-400" />
        )}
      </div>

      <div className="flex-1 min-w-0 space-y-3">
        {kpis && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <KpiTile label="Publicações" value={String(kpis.publications)} delayMs={0} />
            <KpiTile
              label="Scopus / WoS"
              value={`${kpis.scopus} / ${kpis.wos}`}
              sub={`${kpis.indexed_pct}%`}
              delayMs={55}
            />
            <KpiTile
              label="Quartil Q1"
              value={String(kpis.q1)}
              sub={`OA: ${kpis.open_access_pct}%`}
              delayMs={110}
            />
            <KpiTile
              label="Citações"
              value={String(kpis.citations)}
              sub={`Média ${kpis.avg_citations}`}
              delayMs={165}
            />
          </div>
        )}

        {annual.length > 1 && (
          <div className="rounded-xl bg-neutral-900/70 border border-neutral-800/80 p-3.5">
            <div className="flex items-center justify-between mb-2.5">
              <span className="text-[11px] font-mono uppercase tracking-wider text-neutral-400">
                Evolução Anual
              </span>
              <span className="text-[11px] font-mono text-neutral-500">
                Total vs Indexadas (Scopus/WoS)
              </span>
            </div>
            <div className="flex items-end gap-2 h-24 pt-2">
              {annual.map((point) => {
                const totalPct = Math.max((point.publications / maxAnnual) * 100, 4);
                const idxPct = Math.max((point.indexed_scopus_or_wos / maxAnnual) * 100, 0);
                return (
                  <div key={point.year} className="flex-1 flex flex-col items-center gap-1 h-full">
                    <div className="w-full flex-1 flex items-end justify-center gap-1">
                      <div
                        className="w-3 rounded-t bg-neutral-200 animate-chat-bar-grow"
                        style={{ height: `${totalPct}%` }}
                        title={`${point.year}: ${point.publications} publicações`}
                      />
                      <div
                        className="w-3 rounded-t bg-emerald-500/80 animate-chat-bar-grow"
                        style={{ height: `${idxPct}%`, animationDelay: "80ms" }}
                        title={`${point.year}: ${point.indexed_scopus_or_wos} indexadas`}
                      />
                    </div>
                    <span className="text-[10px] font-mono text-neutral-400">{point.year}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        <div className="space-y-1">{renderFormattedLines(visibleContent, isTyping)}</div>

        {!isTyping && message.report_bundle && (
          <div className="flex flex-wrap items-center gap-2 pt-1 animate-chat-step-enter">
            <button
              type="button"
              disabled={downloading !== null}
              onClick={() => void handleDownload("pdf")}
              className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white text-black text-xs font-medium hover:bg-neutral-200 transition-colors disabled:opacity-50"
            >
              <FileText className="w-3.5 h-3.5" />
              {downloading === "pdf" ? "A descarregar..." : "Descarregar PDF"}
            </button>
            <button
              type="button"
              disabled={downloading !== null}
              onClick={() => void handleDownload("excel")}
              className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-neutral-900 border border-neutral-700 text-neutral-100 text-xs font-medium hover:bg-neutral-800 transition-colors disabled:opacity-50"
            >
              <FileSpreadsheet className="w-3.5 h-3.5 text-emerald-400" />
              {downloading === "excel" ? "A descarregar..." : "Descarregar Excel (7 folhas)"}
            </button>
            <span className="text-[11px] font-mono text-neutral-500">
              ID: {message.report_bundle.reproducibility_id}
            </span>
          </div>
        )}

        {!isTyping && (message.sources_json.length > 0 || (message.plan && message.plan.length > 0)) && (
          <div className="pt-1 animate-chat-step-enter">
            <button
              type="button"
              onClick={() => setShowProvenance((s) => !s)}
              className="inline-flex items-center gap-1.5 text-[11px] font-mono text-neutral-500 hover:text-neutral-300 transition-colors"
            >
              {showProvenance ? (
                <ChevronDown className="w-3.5 h-3.5" />
              ) : (
                <ChevronRight className="w-3.5 h-3.5" />
              )}
              <Database className="w-3 h-3 text-emerald-400" />
              Fontes ({message.sources_json.length}) & Rastreabilidade
            </button>
            {showProvenance && (
              <div className="mt-2 rounded-lg bg-neutral-900/80 border border-neutral-800 p-3 space-y-2 text-xs">
                {message.plan && message.plan.length > 0 && (
                  <div>
                    <div className="text-[10px] font-mono uppercase text-neutral-500 mb-1">
                      Plano executado
                    </div>
                    <ol className="list-decimal list-inside space-y-0.5 text-neutral-400">
                      {message.plan.map((step, i) => (
                        <li key={i}>{step}</li>
                      ))}
                    </ol>
                  </div>
                )}
                {message.sources_json.length > 0 && (
                  <div>
                    <div className="text-[10px] font-mono uppercase text-neutral-500 mb-1">
                      Versões das fontes
                    </div>
                    <div className="space-y-1">
                      {message.sources_json.map((src, i) => (
                        <div key={i} className="font-mono text-[11px] text-neutral-300">
                          {src.label} · v{src.version} · {src.record_count} reg. ·{" "}
                          <span className="text-neutral-500">{src.synced_at.slice(0, 19)} UTC</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function KpiTile({
  label,
  value,
  sub,
  delayMs = 0,
}: {
  label: string;
  value: string;
  sub?: string;
  delayMs?: number;
}) {
  return (
    <div
      className="rounded-xl bg-neutral-900 border border-neutral-800/90 px-3 py-2.5 animate-chat-msg-enter"
      style={{ animationDelay: `${delayMs}ms` }}
    >
      <div className="text-[10px] font-mono uppercase tracking-wider text-neutral-500">{label}</div>
      <div className="text-lg font-semibold text-white tracking-tight mt-0.5">{value}</div>
      {sub && <div className="text-[11px] font-mono text-emerald-400/90">{sub}</div>}
    </div>
  );
}
