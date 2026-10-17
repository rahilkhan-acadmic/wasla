"use client";

import { useEffect, useState } from "react";
import { hasValidSession, signOut } from "../lib/auth";
import LoginForm from "./LoginForm";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);

  useEffect(() => {
    setAuthenticated(hasValidSession());
  }, []);

  if (authenticated === null) {
    return null;
  }

  if (!authenticated) {
    return <LoginForm onAuthenticated={() => setAuthenticated(true)} />;
  }

  return (
    <>
      <button
        type="button"
        className="sign-out"
        onClick={() => {
          signOut();
          setAuthenticated(false);
        }}
      >
        Sign out
      </button>
      {children}
    </>
  );
}
