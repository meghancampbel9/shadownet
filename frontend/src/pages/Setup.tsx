import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";

export function SetupPage() {
  const navigate = useNavigate();
  const { setBackend, baseUrl } = useAuth();
  const [url, setUrl] = useState(baseUrl || "");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleConnect() {
    const trimmed = url.replace(/\/+$/, "").trim();
    if (!trimmed) return;
    setLoading(true);
    setError(null);
    setStatus(null);
    try {
      const data = await api.checkHealth(trimmed);
      setStatus(`Connected: ${data.agent} (${data.owner})`);
      setBackend(trimmed);
      setTimeout(() => navigate("/login"), 600);
    } catch (e: any) {
      setError(`Could not reach ${trimmed}/health — ${e.message}`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <div className="w-full max-w-md space-y-6">
        <div>
          <h1 className="text-accent text-xl font-semibold tracking-wider">shadownet</h1>
          <p className="text-muted text-xs mt-2 leading-relaxed">
            Enter the URL of your shadownet backend. This is the server you deployed — there is no central server.
          </p>
        </div>

        <div className="space-y-2">
          <label className="text-[10px] uppercase tracking-widest text-muted">Backend URL</label>
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleConnect()}
            placeholder="https://shadownet.yourdomain.com"
            className="w-full bg-surface-2 border border-border rounded px-3 py-2.5 text-sm text-fg placeholder:text-zinc-600 focus:outline-none focus:border-accent/50"
          />
        </div>

        {status && (
          <div className="border border-accent/40 bg-accent/5 rounded px-3 py-2">
            <p className="text-accent text-xs">{status}</p>
          </div>
        )}
        {error && <p className="text-red-400 text-xs">{error}</p>}

        <button
          onClick={handleConnect}
          disabled={loading || !url.trim()}
          className="w-full bg-accent text-surface-0 font-semibold text-sm py-2.5 rounded hover:bg-accent/90 disabled:opacity-40 transition-all"
        >
          {loading ? "Connecting..." : "Connect"}
        </button>
      </div>
    </div>
  );
}
