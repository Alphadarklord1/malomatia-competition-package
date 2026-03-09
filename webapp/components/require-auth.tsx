"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "./auth-provider";

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { ready, user } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (ready && !user) {
      router.replace("/login");
    }
  }, [ready, router, user]);

  if (!ready || !user) {
    return <div className="panel">Checking session...</div>;
  }

  return <>{children}</>;
}
