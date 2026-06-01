import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Key, Link2, Copy, Check } from "lucide-react";

function CopyField({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="space-y-1">
      <label className="text-[10px] uppercase tracking-widest text-muted">{label}</label>
      <div className="flex items-center gap-2 bg-surface-0 border border-border rounded p-2">
        <span className="text-[11px] text-fg font-mono break-all flex-1">{value}</span>
        <button
          onClick={() => { navigator.clipboard.writeText(value); setCopied(true); setTimeout(() => setCopied(false), 1200); }}
          className="text-muted hover:text-accent shrink-0" title="Copy">
          {copied ? <Check size={13} className="text-accent" /> : <Copy size={13} />}
        </button>
      </div>
    </div>
  );
}

export function ConnectPage() {
  const health = useQuery({ queryKey: ["health"], queryFn: api.getHealth });
  const mint = useMutation({ mutationFn: () => api.mintConnect("handoff") });

  return (
    <div className="space-y-8 max-w-2xl">
      <div>
        <h1 className="text-lg font-semibold">Connect a host agent</h1>
        <p className="text-xs text-muted mt-1">
          Generate a one-time <span className="font-mono">shadow://connect</span> link to pair Claude Code,
          Hermes, or any MCP host with this Sidecar.
        </p>
      </div>

      <section className="space-y-3">
        <h2 className="text-xs uppercase tracking-widest text-muted">This Shadow</h2>
        <div className="bg-surface-1 border border-border rounded p-4 space-y-3">
          {health.data && (
            <>
              <div className="flex items-start gap-2">
                <Key size={12} className="text-accent mt-0.5 shrink-0" />
                <div className="min-w-0">
                  <span className="text-muted text-[10px] uppercase tracking-widest block">Public key</span>
                  <span className="text-fg text-xs font-mono break-all">{health.data.pk}</span>
                </div>
              </div>
              <CopyField label="Connection URI (share with peers)" value={health.data.connectionUri} />
            </>
          )}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-xs uppercase tracking-widest text-muted">Onboard a host LLM</h2>
        <div className="bg-surface-1 border border-border rounded p-4 space-y-4">
          <button onClick={() => mint.mutate()} disabled={mint.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-accent text-surface-0 text-xs font-semibold rounded disabled:opacity-40">
            <Link2 size={14} />
            {mint.isPending ? "Generating…" : "Generate connect link"}
          </button>
          {mint.data && (
            <div className="space-y-3">
              <CopyField label="shadow://connect (single-use)" value={mint.data.connectUri} />
              <p className="text-[10px] text-muted">
                Single-use, expires {new Date(mint.data.expiresAt).toLocaleString()}. Paste it into your host
                agent's Shadownet plugin configuration.
              </p>
            </div>
          )}
          {mint.error && <p className="text-red-400 text-xs">{(mint.error as Error).message}</p>}
        </div>
      </section>
    </div>
  );
}
