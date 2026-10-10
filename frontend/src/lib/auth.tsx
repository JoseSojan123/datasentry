import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { get, getToken, post, setToken, setUnauthorizedHandler } from "./api";
import type { Role, Session, User, Workspace } from "./types";

interface AuthState {
  user: User | null;
  workspace: Workspace | null;
  status: "loading" | "authenticated" | "anonymous";
  login: (email: string, password: string) => Promise<void>;
  register: (data: { email: string; password: string; display_name: string; workspace_name?: string }) => Promise<void>;
  startDemo: (loadSampleData?: boolean) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
  can: (role: Role) => boolean;
}

const Ctx = createContext<AuthState | null>(null);
const RANK: Record<Role, number> = { viewer: 0, editor: 1, admin: 2 };

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [status, setStatus] = useState<AuthState["status"]>(() => (getToken() ? "loading" : "anonymous"));

  const clear = useCallback(() => {
    setToken(null);
    setUser(null);
    setWorkspace(null);
    setStatus("anonymous");
    qc.clear();
  }, [qc]);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setStatus("anonymous");
      return;
    }
    try {
      const me = await get<{ user: User; workspace: Workspace }>("/auth/me");
      setUser(me.user);
      setWorkspace(me.workspace);
      setStatus("authenticated");
    } catch {
      clear();
    }
  }, [clear]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      if (getToken()) clear();
    });
    void refresh();
  }, [refresh, clear]);

  const accept = useCallback(
    (s: Session) => {
      qc.clear();
      setToken(s.access_token);
      setUser(s.user);
      setWorkspace(s.workspace);
      setStatus("authenticated");
    },
    [qc],
  );

  const value = useMemo<AuthState>(
    () => ({
      user,
      workspace,
      status,
      login: async (email, password) => accept(await post<Session>("/auth/login", { email, password })),
      register: async (data) => accept(await post<Session>("/auth/register", data)),
      startDemo: async (load = true) => accept(await post<Session>("/auth/demo", { load_sample_data: load })),
      logout: clear,
      refresh,
      can: (role) => !!user && RANK[user.role] >= RANK[role],
    }),
    [user, workspace, status, accept, clear, refresh],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth outside AuthProvider");
  return c;
}
