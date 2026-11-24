import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  FileSpreadsheet,
  RefreshCw,
  ShieldAlert,
  Upload,
} from "lucide-react";

import { ApiError, api } from "@/services/api";
import type {
  AuditLogItem,
  ExcelImportRecord,
  ExcelPreviewResponse,
  SourceSnapshot,
  UserProfile,
} from "@/types/api";

interface AdminPageProps {
  user: UserProfile;
  mode: "admin" | "audit";
}

export function AdminPage({ user, mode }: AdminPageProps) {
  const isAdmin = user.role === "admin";
  const [snapshots, setSnapshots] = useState<SourceSnapshot[]>([]);
  const [imports, setImports] = useState<ExcelImportRecord[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLogItem[]>([]);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ExcelPreviewResponse | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const refreshData = useCallback(async () => {
    try {
      if (mode === "audit") {
        setAuditLogs(await api.listAuditLogs());
      } else {
        setSnapshots(await api.listSnapshots());
        if (isAdmin) {
          setImports(await api.listExcelImports());
        }
      }
    } catch (err) {
      setFeedback({
        type: "err",
        text: err instanceof ApiError ? err.message : "Erro ao carregar dados.",
      });
    }
  }, [isAdmin, mode]);

  useEffect(() => {
    void refreshData();
  }, [refreshData]);

  const handlePortalSync = async (nocache: boolean) => {
    setBusy(nocache ? "sync-force" : "sync");
    setFeedback(null);
    try {
      const snap = await api.syncPortal(nocache);
      setFeedback({
        type: "ok",
        text: `Portal sincronizado (v${snap.source_version ?? "?"}): ${snap.record_count} registos (${snap.records_created} criados, ${snap.records_updated} atualizados, ${snap.records_removed} removidos).`,
      });
      await refreshData();
    } catch (err) {
      setFeedback({
        type: "err",
        text: err instanceof ApiError ? err.message : "Erro na sincronização do Portal.",
      });
    } finally {
      setBusy(null);
    }
  };

  const handlePreviewExcel = async () => {
    if (!selectedFile) return;
    setBusy("preview");
    setFeedback(null);
    try {
      const res = await api.previewExcel(selectedFile);
      setPreview(res);
    } catch (err) {
      setFeedback({
        type: "err",
        text: err instanceof ApiError ? err.message : "Erro ao pré-visualizar Excel.",
      });
    } finally {
      setBusy(null);
    }
  };

  const handleConfirmImport = async () => {
    if (!selectedFile) return;
    setBusy("import");
    setFeedback(null);
    try {
      const res = await api.importExcel(selectedFile, preview?.selected_sheet);
      setFeedback({
        type: "ok",
        text: `Importação concluída (${res.filename}): ${res.created_rows} criados, ${res.updated_rows} atualizados, ${res.duplicate_count} duplicados sinalizados.`,
      });
      setPreview(null);
      setSelectedFile(null);
      await refreshData();
    } catch (err) {
      setFeedback({
        type: "err",
        text: err instanceof ApiError ? err.message : "Erro ao importar Excel.",
      });
    } finally {
      setBusy(null);
    }
  };

  if (mode === "audit") {
    return (
      <div className="flex-1 overflow-y-auto p-6 max-w-5xl mx-auto w-full space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-white">
              Registo de Auditoria
            </h1>
            <p className="text-sm text-neutral-400 mt-1">
              Operações relevantes, acessos negados por RBAC e execuções do agente.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void refreshData()}
            className="px-3 py-1.5 rounded-lg bg-neutral-900 border border-neutral-800 text-xs text-neutral-300 hover:text-white flex items-center gap-1.5"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Atualizar
          </button>
        </div>

        <div className="rounded-xl border border-neutral-800 bg-neutral-900/60 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-neutral-900 text-neutral-400 font-mono uppercase text-[10px]">
                <tr>
                  <th className="px-4 py-3">Data (UTC)</th>
                  <th className="px-4 py-3">Ação</th>
                  <th className="px-4 py-3">Perfil</th>
                  <th className="px-4 py-3">Estado</th>
                  <th className="px-4 py-3">Recurso</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-800/80">
                {auditLogs.map((log) => (
                  <tr key={log.id} className="hover:bg-neutral-900/80">
                    <td className="px-4 py-2.5 font-mono text-neutral-400 whitespace-nowrap">
                      {log.created_at.slice(0, 19).replace("T", " ")}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-neutral-200">{log.action}</td>
                    <td className="px-4 py-2.5 text-neutral-400">{log.user_role ?? "-"}</td>
                    <td className="px-4 py-2.5">
                      <span
                        className={
                          log.status === "denied"
                            ? "inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-red-950/80 border border-red-900 text-red-300 font-mono text-[10px]"
                            : "inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-950/60 border border-emerald-900/70 text-emerald-300 font-mono text-[10px]"
                        }
                      >
                        {log.status === "denied" && <ShieldAlert className="w-3 h-3" />}
                        {log.status}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 font-mono text-neutral-400 truncate max-w-xs">
                      {log.resource_type}
                      {log.resource_id ? ` · ${log.resource_id}` : ""}
                    </td>
                  </tr>
                ))}
                {auditLogs.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-neutral-500">
                      Sem registos de auditoria.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 max-w-5xl mx-auto w-full space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-white">
          Fontes de Dados & Administração
        </h1>
        <p className="text-sm text-neutral-400 mt-1">
          Sincronização da API do Portal Científico e importação validada de Excel de docentes.
        </p>
      </div>

      {feedback && (
        <div
          className={
            feedback.type === "ok"
              ? "rounded-xl border border-emerald-900/70 bg-emerald-950/40 px-4 py-3 text-xs text-emerald-200 flex items-center gap-2"
              : "rounded-xl border border-red-900/70 bg-red-950/40 px-4 py-3 text-xs text-red-200 flex items-center gap-2"
          }
        >
          {feedback.type === "ok" ? (
            <CheckCircle2 className="w-4 h-4 shrink-0" />
          ) : (
            <AlertTriangle className="w-4 h-4 shrink-0" />
          )}
          {feedback.text}
        </div>
      )}

      {isAdmin && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Card 1: Portal Científico */}
          <div className="rounded-2xl bg-neutral-900 border border-neutral-800 p-5 space-y-4">
            <div>
              <h2 className="text-sm font-semibold text-white">Portal Científico do ISLA (API)</h2>
              <p className="text-xs text-neutral-400 mt-1">
                Consulta <code className="font-mono text-emerald-400">GET /api/powerbi/publications</code>{" "}
                no backend com cache de 24h. O token Bearer nunca é exposto ao navegador.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => void handlePortalSync(false)}
                className="px-3.5 py-2 rounded-lg bg-white text-black text-xs font-medium hover:bg-neutral-200 disabled:opacity-50 flex items-center gap-2"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${busy === "sync" ? "animate-spin" : ""}`} />
                Sincronizar (cache 24h)
              </button>
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => void handlePortalSync(true)}
                className="px-3.5 py-2 rounded-lg bg-neutral-950 border border-neutral-700 text-neutral-200 text-xs font-medium hover:bg-neutral-800 disabled:opacity-50"
              >
                Forçar atualização (nocache=1)
              </button>
            </div>
          </div>

          {/* Card 2: Excel da Intranet */}
          <div className="rounded-2xl bg-neutral-900 border border-neutral-800 p-5 space-y-4">
            <div>
              <h2 className="text-sm font-semibold text-white">Excel de Docentes da Intranet</h2>
              <p className="text-xs text-neutral-400 mt-1">
                Validação em duas fases: pré-visualiza folhas, duplicados, erros de cabeçalho e
                códigos brutos antes de gravar na base de dados.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <label className="cursor-pointer px-3 py-2 rounded-lg bg-neutral-950 border border-dashed border-neutral-700 hover:border-neutral-500 text-xs text-neutral-300 flex items-center gap-2">
                <Upload className="w-3.5 h-3.5" />
                <span className="truncate max-w-[200px]">
                  {selectedFile ? selectedFile.name : "Selecionar .xlsx"}
                </span>
                <input
                  type="file"
                  accept=".xlsx"
                  className="hidden"
                  onChange={(e) => {
                    setSelectedFile(e.target.files?.[0] ?? null);
                    setPreview(null);
                  }}
                />
              </label>
              <button
                type="button"
                disabled={!selectedFile || busy !== null}
                onClick={() => void handlePreviewExcel()}
                className="px-3 py-2 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-xs font-medium text-white disabled:opacity-40 flex items-center gap-1.5"
              >
                <FileSpreadsheet className="w-3.5 h-3.5 text-emerald-400" />
                {busy === "preview" ? "A analisar..." : "Pré-visualizar"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Pré-visualização de Excel */}
      {preview && (
        <div className="rounded-2xl bg-neutral-900 border border-emerald-900/60 p-5 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-white">
                Pré-visualização: {preview.filename} (folha: {preview.selected_sheet})
              </h3>
              <p className="text-xs text-neutral-400 font-mono mt-0.5">
                {preview.total_rows} registos · {preview.with_ciencia_vitae_id} com Ciência Vitae (
                {preview.distinct_ciencia_vitae_ids} distintos) · {preview.duplicates.length}{" "}
                duplicados · {preview.warnings.length} avisos · {preview.errors.length} erros
              </p>
            </div>
            <button
              type="button"
              disabled={preview.errors.length > 0 || busy !== null}
              onClick={() => void handleConfirmImport()}
              className="px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-black text-xs font-semibold disabled:opacity-40"
            >
              {busy === "import" ? "A importar..." : "Confirmar importação"}
            </button>
          </div>

          {preview.warnings.length > 0 && (
            <div className="rounded-lg bg-neutral-950 border border-neutral-800 p-3 space-y-1">
              <div className="text-[10px] font-mono uppercase text-amber-400">
                Avisos de qualidade detetados
              </div>
              {preview.warnings.slice(0, 8).map((w, i) => (
                <div key={i} className="text-xs text-neutral-300">
                  Linha {w.row}: {w.message}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Histórico de Snapshots */}
      <div className="rounded-2xl bg-neutral-900/60 border border-neutral-800 overflow-hidden">
        <div className="px-4 py-3 border-b border-neutral-800 flex items-center justify-between">
          <h3 className="text-xs font-mono uppercase tracking-wider text-neutral-400">
            Histórico de Snapshots ({snapshots.length})
          </h3>
          {imports.length > 0 && (
            <span className="text-[11px] font-mono text-neutral-500">
              {imports.length} importações Excel registadas
            </span>
          )}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-neutral-900 text-neutral-400 font-mono uppercase text-[10px]">
              <tr>
                <th className="px-4 py-2.5">Fonte</th>
                <th className="px-4 py-2.5">Versão</th>
                <th className="px-4 py-2.5">Registos</th>
                <th className="px-4 py-2.5">Alterações (+ / ~ / -)</th>
                <th className="px-4 py-2.5">Data (UTC)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-800/80">
              {snapshots.map((s) => (
                <tr key={s.id}>
                  <td className="px-4 py-2.5 text-neutral-200 font-mono">
                    {s.source_type} · {s.endpoint_or_filename}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-emerald-400">
                    {s.source_version ?? s.content_hash.slice(0, 10)}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-neutral-300">{s.record_count}</td>
                  <td className="px-4 py-2.5 font-mono text-neutral-400">
                    +{s.records_created} / ~{s.records_updated} / -{s.records_removed}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-neutral-400">
                    {s.synced_at.slice(0, 19).replace("T", " ")}
                  </td>
                </tr>
              ))}
              {snapshots.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-neutral-500">
                    Nenhuma sincronização ou importação registada ainda.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
