import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { Plus, Shield, X, Key } from "lucide-react";

function shortId(id: string): string {
  if (id.includes("@")) return id;
  return id.length > 28 ? `${id.slice(0, 14)}…${id.slice(-6)}` : id;
}

export function ContactsPage() {
  const queryClient = useQueryClient();
  const { data: contacts, isLoading } = useQuery({ queryKey: ["contacts"], queryFn: api.listContacts });
  const [showAdd, setShowAdd] = useState(false);

  const [identifier, setIdentifier] = useState("");
  const [name, setName] = useState("");

  const addMutation = useMutation({
    mutationFn: async () => api.addContact({ identifier, name: name || undefined }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contacts"] });
      setShowAdd(false);
      setIdentifier("");
      setName("");
    },
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Contacts</h1>
        <button onClick={() => setShowAdd(!showAdd)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-accent text-surface-0 text-xs font-semibold rounded hover:bg-accent/90 transition-colors">
          {showAdd ? <X size={14} /> : <Plus size={14} />}
          {showAdd ? "Cancel" : "Add Contact"}
        </button>
      </div>

      {showAdd && (
        <form onSubmit={(e) => { e.preventDefault(); addMutation.mutate(); }}
          className="bg-surface-1 border border-border rounded p-4 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-1">
              <label className="text-[10px] uppercase tracking-widest text-muted">
                Shadowname or connection URI<span className="text-red-400 ml-0.5">*</span>
              </label>
              <input value={identifier} onChange={(e) => setIdentifier(e.target.value)}
                placeholder="alice@sh4dow.org or shadow://key:z6Mk…@host:port" className="input" />
            </div>
            <div className="space-y-1">
              <label className="text-[10px] uppercase tracking-widest text-muted">Name</label>
              <input value={name} onChange={(e) => setName(e.target.value)}
                placeholder="Optional display name" className="input" />
            </div>
          </div>

          {addMutation.error && <p className="text-red-400 text-xs">{(addMutation.error as Error).message}</p>}
          <button type="submit" disabled={addMutation.isPending || !identifier}
            className="bg-accent text-surface-0 text-xs font-semibold px-4 py-2 rounded disabled:opacity-40">
            {addMutation.isPending ? "Resolving…" : "Add Contact"}
          </button>
        </form>
      )}

      {isLoading && <p className="text-muted text-xs">Loading...</p>}

      <div className="space-y-2">
        {contacts?.map((c) => {
          const allowed = c.grants?.messaging ?? false;
          return (
            <Link key={c.id} to={`/contacts/${c.id}`}
              className="flex items-center gap-3 bg-surface-1 border border-border rounded p-3 hover:border-accent/30 transition-colors">
              <div className="w-9 h-9 rounded bg-accent/10 flex items-center justify-center text-accent text-sm font-bold shrink-0">
                {c.name.charAt(0).toUpperCase()}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm text-fg truncate">{c.name}</p>
                <p className="text-[10px] text-muted truncate flex items-center gap-1">
                  <Key size={9} className="text-accent/80 shrink-0" />
                  <span className="font-mono">{shortId(c.identifier)}</span>
                </p>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                {c.credentials?.length > 0 && (
                  <span className="text-[10px] text-accent/80 px-2 py-0.5 bg-accent/10 rounded">
                    {c.credentials.length} cred
                  </span>
                )}
                {c.label && <span className="text-[10px] text-muted px-2 py-0.5 bg-surface-2 rounded">{c.label}</span>}
                <span className="flex items-center gap-1 text-[10px] text-muted">
                  <Shield size={10} />{allowed ? "Allowed" : "Blocked"}
                </span>
              </div>
            </Link>
          );
        })}
        {contacts?.length === 0 && <p className="text-muted text-xs">No contacts yet. Add one to get started.</p>}
      </div>
    </div>
  );
}
