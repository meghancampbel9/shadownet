import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Users, MessageSquare, Shield, Fingerprint } from "lucide-react";

export function DashboardPage() {
  const { userName } = useAuth();
  const contacts = useQuery({ queryKey: ["contacts"], queryFn: api.listContacts });
  const messages = useQuery({ queryKey: ["messages"], queryFn: () => api.listMessages(10) });

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-lg font-semibold text-fg">Welcome back, {userName}</h1>
        <p className="text-xs text-muted mt-1">Agent-to-agent communication dashboard</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <StatCard icon={Users} label="Contacts" value={contacts.data?.length ?? "—"} to="/contacts" />
        <StatCard icon={MessageSquare} label="Messages" value={messages.data?.length ?? "—"} to="/messages" />
      </div>

      {(contacts.data?.length ?? 0) > 0 && (
        <section className="space-y-3">
          <h2 className="text-xs uppercase tracking-widest text-muted">Contacts</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {contacts.data!.slice(0, 6).map((c) => {
              const allowed = c.grants?.messaging ?? false;
              return (
                <Link key={c.id} to={`/contacts/${c.id}`}
                  className="flex items-center gap-3 bg-surface-1 border border-border rounded p-3 hover:border-accent/30 transition-colors">
                  <div className="w-8 h-8 rounded bg-accent/10 flex items-center justify-center text-accent text-xs font-bold">
                    {c.name.charAt(0).toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <p className="text-sm text-fg truncate">{c.name}</p>
                      {c.did && <Fingerprint size={10} className="text-purple-400 shrink-0" />}
                    </div>
                    {c.shadowname ? (
                      <p className="text-[10px] text-accent/80 font-mono">@{c.shadowname}</p>
                    ) : c.label ? (
                      <p className="text-[10px] text-muted">{c.label}</p>
                    ) : null}
                  </div>
                  <div className="flex items-center gap-1 text-[10px] text-muted">
                    <Shield size={10} /> {allowed ? "Allowed" : "Blocked"}
                  </div>
                </Link>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}

function StatCard({ icon: Icon, label, value, to }: { icon: any; label: string; value: number | string; to: string }) {
  return (
    <Link to={to} className="bg-surface-1 border border-border rounded p-4 hover:border-accent/30 transition-colors">
      <div className="flex items-center gap-3">
        <Icon size={18} className="text-accent" />
        <div>
          <p className="text-xl font-semibold text-fg">{value}</p>
          <p className="text-[10px] uppercase tracking-widest text-muted">{label}</p>
        </div>
      </div>
    </Link>
  );
}
