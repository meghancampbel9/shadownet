import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react";
import type { TokenResponse } from "./types";

interface AuthState {
  token: string | null;
  userId: string | null;
  userName: string | null;
  baseUrl: string | null;
  isReady: boolean;
  login: (resp: TokenResponse) => void;
  logout: () => void;
  setBackend: (url: string) => void;
}

const AuthContext = createContext<AuthState>(null!);

export function useAuth() {
  return useContext(AuthContext);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [userName, setUserName] = useState<string | null>(null);
  const [baseUrl, setBaseUrlState] = useState<string | null>(null);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    setToken(localStorage.getItem("shadownet_token"));
    setUserId(localStorage.getItem("shadownet_user_id"));
    setUserName(localStorage.getItem("shadownet_user_name"));
    setBaseUrlState(localStorage.getItem("shadownet_base_url"));
    setIsReady(true);
  }, []);

  const login = useCallback((resp: TokenResponse) => {
    localStorage.setItem("shadownet_token", resp.access_token);
    localStorage.setItem("shadownet_user_id", resp.user_id);
    localStorage.setItem("shadownet_user_name", resp.name);
    setToken(resp.access_token);
    setUserId(resp.user_id);
    setUserName(resp.name);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem("shadownet_token");
    localStorage.removeItem("shadownet_user_id");
    localStorage.removeItem("shadownet_user_name");
    setToken(null);
    setUserId(null);
    setUserName(null);
  }, []);

  const setBackend = useCallback((url: string) => {
    localStorage.setItem("shadownet_base_url", url);
    setBaseUrlState(url);
  }, []);

  return (
    <AuthContext.Provider value={{ token, userId, userName, baseUrl, isReady, login, logout, setBackend }}>
      {children}
    </AuthContext.Provider>
  );
}
