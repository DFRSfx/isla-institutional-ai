import { useEffect, useState } from "react";
import { Check, ChevronDown, ChevronRight } from "lucide-react";

interface AgentThinkingIndicatorProps {
  liveStageLabel?: string | null;
  liveStages?: string[];
  liveThinking?: string;
}

export function AgentThinkingIndicator({
  liveStageLabel,
  liveStages = [],
  liveThinking = "",
}: AgentThinkingIndicatorProps = {}) {
  const [elapsedMs, setElapsedMs] = useState(0);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    const startedAt = performance.now();
    const timer = window.setInterval(() => {
      setElapsedMs(performance.now() - startedAt);
    }, 250);
    return () => window.clearInterval(timer);
  }, []);

  const totalSec = Math.floor(elapsedMs / 1000);
  const timeLabel = totalSec >= 60 ? `${Math.floor(totalSec / 60)}m ${totalSec % 60}s` : `${totalSec}s`;
  const headline = liveStageLabel || "A processar pedido...";
  const hasDetails = liveStages.length > 0 || Boolean(liveThinking.trim());

  return (
    <div
      className="pl-10 animate-chat-msg-enter"
      role="status"
      aria-live="polite"
      aria-label={headline}
    >
      <div className="inline-flex flex-col max-w-2xl rounded-xl bg-neutral-900/80 border border-neutral-800/80 overflow-hidden">
        <button
          type="button"
          onClick={() => hasDetails && setExpanded((v) => !v)}
          className="flex items-center justify-between gap-4 px-3.5 py-2 text-left hover:bg-neutral-800/40 transition-colors"
        >
          <span
            key={headline}
            className="text-xs font-medium truncate animate-chat-shimmer-text animate-chat-step-enter"
          >
            {headline}
          </span>
          <span className="flex items-center gap-1.5 shrink-0 text-xs font-mono tabular-nums text-neutral-500">
            <span>{timeLabel}</span>
            {hasDetails &&
              (expanded ? (
                <ChevronDown className="w-3.5 h-3.5 text-neutral-500" />
              ) : (
                <ChevronRight className="w-3.5 h-3.5 text-neutral-500" />
              ))}
          </span>
        </button>

        {expanded && hasDetails && (
          <div className="px-3.5 pb-3 pt-1.5 border-t border-neutral-800/70 space-y-2 text-xs">
            {liveStages.length > 0 && (
              <div className="space-y-1.5 border-l border-neutral-800 pl-3 ml-1">
                {liveStages.map((step, idx) => {
                  const isCurrent = idx === liveStages.length - 1;
                  return (
                    <div
                      key={`${idx}-${step}`}
                      className="flex items-center gap-2 text-[11px] animate-chat-step-enter"
                    >
                      {isCurrent ? (
                        <span className="h-1.5 w-1.5 rounded-full bg-neutral-400 animate-pulse shrink-0" />
                      ) : (
                        <Check className="w-3 h-3 text-neutral-500 shrink-0" />
                      )}
                      <span className={isCurrent ? "text-neutral-200" : "text-neutral-500"}>
                        {step}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}

            {liveThinking.trim() && (
              <div className="rounded-lg bg-neutral-950/70 border border-neutral-800/70 px-3 py-2 text-[11px] text-neutral-400 font-mono whitespace-pre-wrap leading-relaxed max-h-48 overflow-y-auto">
                {liveThinking}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
