import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowUpIcon,
  BarChart3,
  Database,
  FileSpreadsheet,
  GitCompareArrows,
  Loader2,
  Paperclip,
  PlusIcon,
  UserSearch,
} from "lucide-react";

import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

interface UseAutoResizeTextareaProps {
  minHeight: number;
  maxHeight?: number;
}

function useAutoResizeTextarea({ minHeight, maxHeight }: UseAutoResizeTextareaProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const adjustHeight = useCallback(
    (reset?: boolean) => {
      const textarea = textareaRef.current;
      if (!textarea) return;

      if (reset) {
        textarea.style.height = `${minHeight}px`;
        return;
      }

      textarea.style.height = `${minHeight}px`;
      const newHeight = Math.max(
        minHeight,
        Math.min(textarea.scrollHeight, maxHeight ?? Number.POSITIVE_INFINITY)
      );
      textarea.style.height = `${newHeight}px`;
    },
    [minHeight, maxHeight]
  );

  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = `${minHeight}px`;
    }
  }, [minHeight]);

  useEffect(() => {
    const handleResize = () => adjustHeight();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [adjustHeight]);

  return { textareaRef, adjustHeight };
}

export interface VercelV0ChatProps {
  onSend?: (message: string) => void | Promise<void>;
  onNewChat?: () => void;
  onOpenExcelImport?: () => void;
  canUploadExcel?: boolean;
  isLoading?: boolean;
  compact?: boolean;
  placeholder?: string;
  userRole?: string;
}

export function VercelV0Chat({
  onSend,
  onNewChat,
  onOpenExcelImport,
  canUploadExcel = false,
  isLoading = false,
  compact = false,
  placeholder = "Pergunta sobre publicações, docentes, escolas ou pede um relatório PDF/Excel...",
  userRole,
}: VercelV0ChatProps) {
  const [value, setValue] = useState("");
  const { textareaRef, adjustHeight } = useAutoResizeTextarea({
    minHeight: compact ? 52 : 68,
    maxHeight: 200,
  });

  const submitMessage = async (textToSend?: string) => {
    const trimmed = (textToSend ?? value).trim();
    if (!trimmed || isLoading) return;
    setValue("");
    adjustHeight(true);
    await onSend?.(trimmed);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void submitMessage();
    }
  };

  return (
    <div
      className={cn(
        "flex flex-col items-center w-full mx-auto",
        compact ? "max-w-3xl px-4 pb-4 pt-2" : "max-w-3xl px-4 py-8 space-y-8"
      )}
    >
      {!compact && (
        <div className="text-center space-y-3">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-neutral-800 bg-neutral-900/80 text-[11px] font-mono tracking-wider uppercase text-neutral-400">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            ISLA · Agente Científico & Institucional
          </div>
          <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight text-white">
            O que queres analisar hoje?
          </h1>
          <p className="text-sm text-neutral-400 max-w-xl mx-auto leading-relaxed">
            Consulta o Portal Científico e os dados de docentes em linguagem natural, com cálculos
            determinísticos, citação de fontes e exportação imediata em PDF e Excel.
          </p>
        </div>
      )}

      <div className="w-full">
        <div className="relative bg-neutral-900 rounded-xl border border-neutral-800 shadow-[0_8px_30px_rgb(0,0,0,0.35)] focus-within:border-neutral-700 transition-colors">
          <div className="overflow-y-auto">
            <Textarea
              ref={textareaRef}
              value={value}
              disabled={isLoading}
              onChange={(e) => {
                setValue(e.target.value);
                adjustHeight();
              }}
              onKeyDown={handleKeyDown}
              placeholder={placeholder}
              className={cn(
                "w-full px-4 py-3.5",
                "resize-none",
                "bg-transparent",
                "border-none",
                "text-neutral-100 text-sm leading-relaxed",
                "focus:outline-none",
                "focus-visible:ring-0 focus-visible:ring-offset-0",
                "placeholder:text-neutral-500 placeholder:text-sm",
                compact ? "min-h-[52px]" : "min-h-[68px]"
              )}
              style={{ overflow: "hidden" }}
            />
          </div>

          <div className="flex items-center justify-between px-3 pb-3 pt-1">
            <div className="flex items-center gap-2">
              {canUploadExcel && onOpenExcelImport && (
                <button
                  type="button"
                  onClick={onOpenExcelImport}
                  title="Importar ficheiro Excel de docentes"
                  className="group p-2 hover:bg-neutral-800 rounded-lg transition-colors flex items-center gap-1.5 text-neutral-400 hover:text-white"
                >
                  <Paperclip className="w-4 h-4" />
                  <span className="text-xs hidden sm:inline">Importar Excel</span>
                </button>
              )}
              {!canUploadExcel && (
                <span className="text-[11px] font-mono text-neutral-500 px-2">
                  Enter envia · Shift+Enter nova linha
                </span>
              )}
            </div>

            <div className="flex items-center gap-2">
              {onNewChat && (
                <button
                  type="button"
                  onClick={onNewChat}
                  className="px-2.5 py-1.5 rounded-lg text-xs text-neutral-400 transition-colors border border-dashed border-neutral-700 hover:border-neutral-600 hover:bg-neutral-800 hover:text-neutral-200 flex items-center gap-1"
                >
                  <PlusIcon className="w-3.5 h-3.5" />
                  Nova análise
                </button>
              )}
              <button
                type="button"
                disabled={!value.trim() || isLoading}
                onClick={() => void submitMessage()}
                className={cn(
                  "px-2 py-1.5 rounded-lg text-sm transition-all border flex items-center justify-center",
                  value.trim() && !isLoading
                    ? "bg-white text-black border-white hover:bg-neutral-200 cursor-pointer"
                    : "text-neutral-500 border-neutral-800 bg-neutral-900/50 cursor-not-allowed"
                )}
              >
                {isLoading ? (
                  <Loader2 className="w-4 h-4 animate-spin text-neutral-300" />
                ) : (
                  <ArrowUpIcon
                    className={cn("w-4 h-4", value.trim() ? "text-black" : "text-neutral-500")}
                  />
                )}
                <span className="sr-only">Enviar</span>
              </button>
            </div>
          </div>
        </div>

        {!compact && (
          <div className="flex flex-wrap items-center justify-center gap-2.5 mt-4">
            <ActionButton
              icon={<BarChart3 className="w-3.5 h-3.5 text-emerald-400" />}
              label="Relatório EST (últimos 5 anos)"
              onClick={() =>
                void submitMessage(
                  "Preciso de um relatório da produção científica da EST nos últimos cinco anos, com os docentes mais produtivos, publicações indexadas e evolução anual."
                )
              }
            />
            <ActionButton
              icon={<GitCompareArrows className="w-3.5 h-3.5 text-neutral-300" />}
              label="Comparar 2024 vs 2025"
              onClick={() =>
                void submitMessage(
                  "Mostra-me um relatório institucional do ISLA com comparação entre 2024 e 2025."
                )
              }
            />
            <ActionButton
              icon={<UserSearch className="w-3.5 h-3.5 text-neutral-300" />}
              label={userRole === "faculty" ? "Minhas publicações" : "Produção da ESG"}
              onClick={() =>
                void submitMessage(
                  userRole === "faculty"
                    ? "Mostra-me as minhas publicações e indicadores científicos."
                    : "Quero a produção científica da ESG nos últimos 5 anos com relatório PDF e Excel."
                )
              }
            />
            <ActionButton
              icon={<Database className="w-3.5 h-3.5 text-neutral-300" />}
              label="Estado das fontes"
              onClick={() =>
                void submitMessage("Qual é o estado e a data da última atualização das fontes?")
              }
            />
            {canUploadExcel && onOpenExcelImport && (
              <ActionButton
                icon={<FileSpreadsheet className="w-3.5 h-3.5 text-emerald-400" />}
                label="Importar Excel de Docentes"
                onClick={onOpenExcelImport}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

interface ActionButtonProps {
  icon: React.ReactNode;
  label: string;
  onClick?: () => void;
}

function ActionButton({ icon, label, onClick }: ActionButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-2 px-3.5 py-2 bg-neutral-900 hover:bg-neutral-800 rounded-full border border-neutral-800 hover:border-neutral-700 text-neutral-300 hover:text-white transition-colors"
    >
      {icon}
      <span className="text-xs font-medium">{label}</span>
    </button>
  );
}
