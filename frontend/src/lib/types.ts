export interface TokenResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  name: string;
}

export type GrantType = "messaging";

export const GRANT_TYPES: GrantType[] = ["messaging"];

export interface Credential {
  kind: string;
  issuer: string;
  org: string;
  expiresAt: string;
}

export interface Contact {
  id: string;
  identifier: string;
  name: string;
  public_key: string;
  agent_endpoint: string;
  label: string;
  notes: string;
  profile: Record<string, unknown>;
  allowed: boolean;
  grants: Record<GrantType, boolean>;
  credentials: Credential[];
  added_at: string;
  last_seen: string | null;
  created_at: string;
  updated_at: string;
}

export type MessageDirection = "inbound" | "outbound";

export interface Message {
  id: string;
  message_id: string;
  context_id: string;
  sender: string;
  recipient: string;
  contact_name: string;
  direction: MessageDirection;
  route: string;
  intent: string;
  body: Record<string, unknown>;
  created_at: string;
}

export interface HealthResponse {
  status: string;
  agent: string;
  owner: string;
  subject: string;
  pk: string;
  connectionUri: string;
}

export interface ConnectResponse {
  connectUri: string;
  handoff?: string;
  expiresAt: string;
}
