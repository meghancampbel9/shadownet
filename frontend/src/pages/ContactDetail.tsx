import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { GRANT_TYPES, type GrantType } from "@/lib/types";
import { ArrowLeft, Trash2, Fingerprint, AtSign, Globe, Key } from "lucide-react";

const GRANT_LABELS: Record<GrantType, string> = {
  messaging: "Allow messaging",
};

export function ContactDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: contact, isLoading } = useQuery({
    queryKey: ["contact", id],
    queryFn: () => api.getContact(id!),
    enabled: !!id,
  });

  const grantMutation = useMutation({
    mutationFn: (allowed: boolean) => api.updateGrant(id!, allowed),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["contact", id] }),
  });

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteContact(id!),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["contacts"] }); navigate("/contacts"); },
  });

  if (isLoading || !contact) return <p className="text-muted text-xs">Loading...</p>;

  return (
    <div className="space-y-8">
      <div className="flex items-center gap-3">
        <Link to="/contacts" className="text-muted hover:text-fg transition-colors"><ArrowLeft size={16} /></Link>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-semibold">{contact.name}</h1>
            {contact.shadowname && (
              <span className="text-xs text-accent/80 font-mono">@{contact.shadowname}</span>
            )}
          </div>
          {contact.did ? (
            <p className="text-[10px] text-muted font-mono truncate flex items-center gap-1 mt-0.5">
              <Fingerprint size={10} className="text-green-400 shrink-0" />
              {contact.did}
            </p>
          ) : (
            <p className="text-xs text-muted truncate">{contact.agent_endpoint}</p>
          )}
        </div>
        <button onClick={() => { if (confirm("Delete this contact?")) deleteMutation.mutate(); }}
          className="text-red-400 hover:text-red-300 transition-colors"><Trash2 size={16} /></button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
        <section className="space-y-3">
          <h2 className="text-xs uppercase tracking-widest text-muted">Identity</h2>
          <div className="bg-surface-1 border border-border rounded p-4 space-y-3 text-sm">
            {contact.did && (
              <Row icon={<Fingerprint size={12} className="text-green-400" />} label="DID" value={contact.did} mono />
            )}
            {contact.shadowname && (
              <Row icon={<AtSign size={12} className="text-accent" />} label="Shadowname" value={contact.shadowname} />
            )}
            <Row icon={<Globe size={12} className="text-muted" />} label="Endpoint" value={contact.agent_endpoint} mono />
            {contact.agent_public_key && (
              <Row icon={<Key size={12} className="text-muted" />} label="Legacy Key" value={contact.agent_public_key.slice(0, 24) + "..."} mono />
            )}
          </div>
        </section>

        <section className="space-y-3">
          <h2 className="text-xs uppercase tracking-widest text-muted">Details</h2>
          <div className="bg-surface-1 border border-border rounded p-4 space-y-3 text-sm">
            {contact.label && <Row label="Label" value={contact.label} />}
            {contact.notes && <Row label="Notes" value={contact.notes} />}
            <Row label="Added" value={new Date(contact.created_at).toLocaleDateString()} />
          </div>
        </section>

        <section className="space-y-3 sm:col-span-2">
          <h2 className="text-xs uppercase tracking-widest text-muted">Access Grants</h2>
          <div className="bg-surface-1 border border-border rounded p-4 space-y-2">
            {GRANT_TYPES.map((gt) => (
              <button key={gt} onClick={() => grantMutation.mutate(!contact.grants[gt])}
                className="w-full flex items-center justify-between py-2 px-1 hover:bg-surface-2 rounded transition-colors">
                <div>
                  <p className="text-xs text-fg">{gt}</p>
                  <p className="text-[10px] text-muted">{GRANT_LABELS[gt]}</p>
                </div>
                <div className={`w-8 h-4 rounded-full transition-colors relative ${contact.grants[gt] ? "bg-accent" : "bg-surface-3"}`}>
                  <div className={`w-3 h-3 rounded-full bg-white absolute top-0.5 transition-all ${contact.grants[gt] ? "left-4" : "left-0.5"}`} />
                </div>
              </button>
            ))}
          </div>
        </section>
      </div>

      {!contact.did && (
        <div className="bg-yellow-500/10 border border-yellow-500/30 rounded p-3">
          <p className="text-[11px] text-yellow-300">
            This contact has no DID assigned. A2A handshake auth will be skipped (legacy mode).
            Ask the peer for their DID or resolve their shadowname to upgrade.
          </p>
        </div>
      )}
    </div>
  );
}

function Row({ icon, label, value, mono }: { icon?: React.ReactNode; label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start gap-2">
      {icon && <span className="mt-0.5 shrink-0">{icon}</span>}
      <div className="flex-1 min-w-0">
        <span className="text-muted text-[10px] uppercase tracking-widest block">{label}</span>
        <span className={`text-fg text-xs break-all ${mono ? "font-mono" : ""}`}>{value}</span>
      </div>
    </div>
  );
}
