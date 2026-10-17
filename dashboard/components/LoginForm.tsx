"use client";

import { useState } from "react";
import {
  signIn,
  completeNewPasswordChallenge,
  verifySoftwareToken,
  submitMfaCode,
  AuthChallenge,
} from "../lib/auth";

type Step =
  | "CREDENTIALS"
  | "NEW_PASSWORD"
  | "MFA_SETUP"
  | "MFA_CODE"
  | "MFA_SETUP_CONFIRM";

export default function LoginForm({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [step, setStep] = useState<Step>("CREDENTIALS");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [mfaSecret, setMfaSecret] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function handleChallenge(challenge: AuthChallenge) {
    switch (challenge.type) {
      case "DONE":
        onAuthenticated();
        return;
      case "NEW_PASSWORD_REQUIRED":
        setStep("NEW_PASSWORD");
        return;
      case "MFA_SETUP":
        setMfaSecret(challenge.secretCode);
        setStep("MFA_SETUP_CONFIRM");
        return;
      case "SOFTWARE_TOKEN_MFA":
        setStep("MFA_CODE");
        return;
    }
  }

  async function run(fn: () => Promise<AuthChallenge>) {
    setLoading(true);
    setError(null);
    try {
      handleChallenge(await fn());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section>
      <h2>Sign in</h2>

      {step === "CREDENTIALS" && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run(() => signIn(username, password));
          }}
        >
          <label>
            Username
            <input value={username} onChange={(e) => setUsername(e.target.value)} required />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          <button type="submit" disabled={loading}>
            {loading ? "Signing in..." : "Sign in"}
          </button>
        </form>
      )}

      {step === "NEW_PASSWORD" && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run(() => completeNewPasswordChallenge(newPassword));
          }}
        >
          <p>Set a new password for your first login.</p>
          <label>
            New password
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
            />
          </label>
          <button type="submit" disabled={loading}>
            {loading ? "Setting..." : "Set password"}
          </button>
        </form>
      )}

      {step === "MFA_SETUP_CONFIRM" && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run(() => verifySoftwareToken(code));
          }}
        >
          <p>Scan this secret into an authenticator app (Google Authenticator, Authy, etc.), then enter the 6-digit code it generates:</p>
          <p className="mfa-secret">{mfaSecret}</p>
          <label>
            Authenticator code
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              inputMode="numeric"
              pattern="[0-9]{6}"
              required
            />
          </label>
          <button type="submit" disabled={loading}>
            {loading ? "Verifying..." : "Confirm"}
          </button>
        </form>
      )}

      {step === "MFA_CODE" && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run(() => submitMfaCode(code));
          }}
        >
          <label>
            Authenticator code
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              inputMode="numeric"
              pattern="[0-9]{6}"
              required
            />
          </label>
          <button type="submit" disabled={loading}>
            {loading ? "Verifying..." : "Verify"}
          </button>
        </form>
      )}

      {error && <p className="error-note">{error}</p>}
    </section>
  );
}
