"use client";

import { useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import Logo from "./Logo";
import {
  signIn,
  completeNewPasswordChallenge,
  verifySoftwareToken,
  submitMfaCode,
  AuthChallenge,
} from "../lib/auth";

// Name shown for this account inside the authenticator app.
const TOTP_ISSUER = "Wasla Distress Dashboard";

// Standard otpauth:// URI (Google Authenticator "Key Uri Format") that every
// mainstream authenticator app reads from a QR code. Built and rendered
// entirely in the browser -- the secret is never sent to a QR service.
function otpauthUri(username: string, secret: string): string {
  // encodeURIComponent, not URLSearchParams: the latter encodes spaces as
  // "+", which some authenticator apps then display literally.
  const label = encodeURIComponent(`${TOTP_ISSUER}:${username}`);
  const query = [
    `secret=${encodeURIComponent(secret)}`,
    `issuer=${encodeURIComponent(TOTP_ISSUER)}`,
    "algorithm=SHA1",
    "digits=6",
    "period=30",
  ].join("&");
  return `otpauth://totp/${label}?${query}`;
}

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
    <div className="login-screen">
    <section className="card login-card">
      <div className="login-brand">
        <Logo size={36} />
        <span className="brand-name">WASLA</span>
      </div>
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
          <button type="submit" className="button-primary" disabled={loading}>
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
          <button type="submit" className="button-primary" disabled={loading}>
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
          <p>
            Scan this QR code with an authenticator app (Google Authenticator, Authy, etc.),
            then enter the 6-digit code it generates:
          </p>
          <div className="mfa-qr">
            <QRCodeSVG
              value={otpauthUri(username, mfaSecret)}
              size={200}
              level="M"
              marginSize={4}
              bgColor="#ffffff"
              fgColor="#000000"
              title="Authenticator setup QR code"
            />
          </div>
          <p>Can&apos;t scan it? Enter this key manually instead (time-based):</p>
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
          <button type="submit" className="button-primary" disabled={loading}>
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
          <button type="submit" className="button-primary" disabled={loading}>
            {loading ? "Verifying..." : "Verify"}
          </button>
        </form>
      )}

      {error && <p className="error-note">{error}</p>}
    </section>
    <p className="app-footer">Research/screening tool only — not investment advice.</p>
    </div>
  );
}
