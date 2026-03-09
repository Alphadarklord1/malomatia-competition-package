"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";

import { loadStoredAuth, persistAuth } from "../lib/auth";
import type { AuthUser } from "../lib/types";

type AuthContextValue = {
  user: AuthUser | null;
  ready: boolean;
  signIn: (user: AuthUser) => void;
  signOut: () => void;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setUser(loadStoredAuth());
    setReady(true);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      ready,
      signIn(nextUser) {
        persistAuth(nextUser);
        setUser(nextUser);
      },
      signOut() {
        persistAuth(null);
        setUser(null);
      },
    }),
    [ready, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return value;
}
