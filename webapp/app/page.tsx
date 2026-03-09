"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "../components/auth-provider";

export default function HomePage() {
  const { ready, user } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!ready) {
      return;
    }
    router.replace(user ? "/dashboard" : "/login");
  }, [ready, router, user]);

  return <div className="login-shell">Loading...</div>;
}
