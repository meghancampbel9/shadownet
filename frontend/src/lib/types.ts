export interface TokenResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  name: string;
}

export type GrantType = "messaging";

export const GRANT_TYPES: GrantType[] = ["messaging"];

export interface Contact {
  id: string;
  name: string;
  agent_endpoint: string;
  agent_public_key: string;
  did: string;
  shadowname: string;
  public_key_jwk: string;
  label: string;
  notes: string;
  metadata: Record<string, unknown>;
  allowed: boolean;
  grants: Record<GrantType, boolean>;
  created_at: string;
  updated_at: string;
}

export interface Interaction {
  id: string;
  data_type: string;
  contact: string;
  contact_id: string;
  direction: string;
  status: string;
  data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export type MessageDirection = "inbound" | "outbound";

export interface AgentMessage {
  id: string;
  direction: MessageDirection;
  contact_id: string | null;
  contact_name: string;
  data_type: string;
  status: string;
  data: Record<string, unknown>;
  created_at: string;
}

export interface HealthResponse {
  status: string;
  agent: string;
  owner: string;
  did: string;
  public_key: string;
}
