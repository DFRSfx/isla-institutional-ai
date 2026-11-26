import { useCallback, useEffect, useState } from "react";
import { FileSpreadsheet, FileText, RefreshCw } from "lucide-react";

import { ApiError, api } from "@/services/api";
import type { ReportBundle } from "@/types/api";

export function ReportsPage() {
  const [reports, setReports] = useState<ReportBundle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);

  const loadReports = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setReports(await api.listReports());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Erro ao carregar relatórios.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadReports();
  }, [loadReports]);

  const handleDownload = async (report: ReportBundle, fmt: "pdf" | "excel") => {
    setDownloading(`${report.report_id}-${fmt}`);
    try {
      const url = fmt === "pdf" ? report.pdf_url : report.excel_url;
      const ext = fmt === "pdf" ? "pdf" : "xlsx";
      await api.downloadReport(url, `isla_relatorio_${report.report_id}.${ext}`);
    } finally {
      setDownloading(null);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto p-6 max-w-5xl mx-auto w-full space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-white">Relatórios Gerados</h1>
          <p className="text-sm text-neutral-400 mt-1">
            Histórico de relatórios PDF e Excel gerados, com ID de reprodutibilidade e controlo RBAC.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void loadReports()}
          className="px-3 py-1.5 rounded-lg bg-neutral-900 border border-neutral-800 text-xs text-neutral-300 hover:text-white flex items-center gap-1.5"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Atualizar
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-red-900/70 bg-red-950/40 px-4 py-3 text-xs text-red-200">
          {error}
        </div>
      )}

      <div className="rounded-2xl bg-neutral-900/60 border border-neutral-800 divide-y divide-neutral-800/80">
        {loading ? (
          <div className="p-8 text-center text-xs font-mono text-neutral-500">
            A carregar relatórios...
          </div>
        ) : reports.length === 0 ? (
          <div className="p-8 text-center text-xs text-neutral-500">
            Ainda não foram gerados relatórios. Pede um relatório no Assistente IA (ex.: &ldquo;Relatório da produção científica da EST nos últimos 5 anos&rdquo;).
          </div>
        ) : (
          reports.map((rep) => (
            <div
              key={rep.report_id}
              className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3"
            >
              <div className="min-w-0 space-y-1">
                <div className="text-sm font-medium text-white truncate">{rep.title}</div>
                <div className="text-[11px] font-mono text-neutral-500">
                  ID: {rep.reproducibility_id || rep.report_id.slice(0, 8)} ·{" "}
                  {(rep.created_at || "").slice(0, 19).replace("T", " ")} UTC
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  type="button"
                  disabled={downloading !== null}
                  onClick={() => void handleDownload(rep, "pdf")}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white text-black text-xs font-medium hover:bg-neutral-200 disabled:opacity-50"
                >
                  <FileText className="w-3.5 h-3.5" />
                  PDF
                </button>
                <button
                  type="button"
                  disabled={downloading !== null}
                  onClick={() => void handleDownload(rep, "excel")}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-neutral-900 border border-neutral-700 text-neutral-100 text-xs font-medium hover:bg-neutral-800 disabled:opacity-50"
                >
                  <FileSpreadsheet className="w-3.5 h-3.5 text-emerald-400" />
                  Excel
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
