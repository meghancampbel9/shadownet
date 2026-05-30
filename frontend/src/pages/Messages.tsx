import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { ArrowDownLeft, ArrowUpRight } from "lucide-react";

export function MessagesPage() {
  const { data, isLoading } = useQuery({ queryKey: ["messages"], queryFn: () => api.listMessages(100) });

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold">Message Log</h1>

      {isLoading && <p className="text-muted text-xs">Loading...</p>}

      <div className="space-y-2">
        {data?.map((m) => (
          <div key={m.id} className="bg-surface-1 border border-border rounded p-3">
            <div className="flex items-center gap-2 mb-2">
              {m.direction === "inbound"
                ? <ArrowDownLeft size={12} className="text-blue-400" />
                : <ArrowUpRight size={12} className="text-accent" />}
              <span className="text-xs text-fg font-medium">{m.contact_name || "Unknown"}</span>
              {m.intent && <span className="text-[10px] text-accent/80 px-1.5 py-0.5 bg-accent/10 rounded font-mono">{m.intent.split(":").pop()}</span>}
              <span className="text-[10px] text-muted px-1.5 py-0.5 bg-surface-2 rounded">{m.route}</span>
              <span className="text-[10px] text-muted ml-auto">{new Date(m.created_at).toLocaleString()}</span>
            </div>
            <pre className="text-[11px] text-muted bg-surface-0 rounded p-2 overflow-x-auto max-h-32 whitespace-pre-wrap">
              {JSON.stringify(m.body, null, 2)}
            </pre>
          </div>
        ))}
        {data?.length === 0 && <p className="text-muted text-xs">No messages yet. Messages appear when agents communicate.</p>}
      </div>
    </div>
  );
}
