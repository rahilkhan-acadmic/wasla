"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { hasValidSession, signOut } from "../lib/auth";
import LoginForm from "./LoginForm";

// Lets the app shell's top-bar sign-out button end the session without
// AuthGate having to render any navigation itself.
const SignOutContext = createContext<() => void>(() => {});

export function useSignOut(): () => void {
  return useContext(SignOutContext);
}

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
    <SignOutContext.Provider
      value={() => {
        signOut();
        setAuthenticated(false);
      }}
    >
      {children}
    </SignOutContext.Provider>
  );
}
