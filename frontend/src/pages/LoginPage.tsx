import { useState } from "react";
import { ArrowRight, Lock, Mail, ShieldCheck } from "lucide-react";

import { ApiError, api, setStoredToken } from "@/services/api";
import type { UserProfile } from "@/types/api";

interface LoginPageProps {
  onAuthenticated: (user: UserProfile) => void;
}

export function LoginPage({ onAuthenticated }: LoginPageProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await api.login(email.trim(), password);
      setStoredToken(res.access_token);
      onAuthenticated(res.user);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Não foi possível contactar o servidor.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-neutral-950 flex items-center justify-center px-4">
      <div className="w-full max-w-md space-y-8">
        <div className="space-y-3 text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-neutral-800 bg-neutral-900 text-[11px] font-mono uppercase tracking-wider text-neutral-400">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
            ISLA Institutional AI · MVP v1.0
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-white">
            Acesso Institucional
          </h1>
          <p className="text-sm text-neutral-400">
            Autentica-te para consultar produção científica, gerar relatórios PDF/Excel e aceder às
            ferramentas autorizadas para o teu perfil.
          </p>
        </div>

        <form
          onSubmit={(e) => void handleSubmit(e)}
          className="bg-neutral-900 border border-neutral-800 rounded-2xl p-6 space-y-5 shadow-[0_12px_40px_rgb(0,0,0,0.45)]"
        >
          {error && (
            <div className="rounded-lg border border-red-900/60 bg-red-950/50 px-3.5 py-2.5 text-xs text-red-200">
              {error}
            </div>
          )}

          <div className="space-y-1.5">
            <label htmlFor="email" className="text-xs font-medium text-neutral-300">
              Email institucional
            </label>
            <div className="relative">
              <Mail className="w-4 h-4 text-neutral-500 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                id="email"
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="nome@islagaia.pt"
                className="w-full rounded-lg bg-neutral-950 border border-neutral-800 pl-9 pr-3 py-2.5 text-sm text-white placeholder:text-neutral-600 focus:outline-none focus:border-neutral-600 transition-colors"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="password" className="text-xs font-medium text-neutral-300">
              Palavra-passe
            </label>
            <div className="relative">
              <Lock className="w-4 h-4 text-neutral-500 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                id="password"
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full rounded-lg bg-neutral-950 border border-neutral-800 pl-9 pr-3 py-2.5 text-sm text-white placeholder:text-neutral-600 focus:outline-none focus:border-neutral-600 transition-colors"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-lg bg-white text-black font-medium text-sm py-2.5 px-4 hover:bg-neutral-200 disabled:opacity-50 transition-colors flex items-center justify-center gap-2"
          >
            {loading ? "A autenticar..." : "Entrar"}
            {!loading && <ArrowRight className="w-4 h-4" />}
          </button>
        </form>

        <p className="text-center text-xs text-neutral-500 font-mono">
          RBAC aplicado no backend · Perfis: Administrador · Direção · Docente
        </p>
      </div>
    </div>
  );
}
