// Thin wrapper around amazon-cognito-identity-js's SRP login + MFA
// challenge-response flow. NEXT_PUBLIC_COGNITO_USER_POOL_ID/CLIENT_ID are
// baked in at build time, same convention as lib/api.ts's API_BASE_URL.

import {
  CognitoUser,
  CognitoUserPool,
  CognitoUserSession,
  AuthenticationDetails,
} from "amazon-cognito-identity-js";

const USER_POOL_ID = process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID ?? "";
const CLIENT_ID = process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID ?? "";

const SESSION_STORAGE_KEY = "distress-model-session";

function userPool(): CognitoUserPool {
  return new CognitoUserPool({ UserPoolId: USER_POOL_ID, ClientId: CLIENT_ID });
}

export type AuthChallenge =
  | { type: "NEW_PASSWORD_REQUIRED" }
  | { type: "MFA_SETUP"; secretCode: string; username: string }
  | { type: "SOFTWARE_TOKEN_MFA" }
  | { type: "DONE"; idToken: string };

let _pendingUser: CognitoUser | null = null;
let _pendingAttrs: Record<string, unknown> = {};

export function signIn(username: string, password: string): Promise<AuthChallenge> {
  return new Promise((resolve, reject) => {
    const user = new CognitoUser({ Username: username, Pool: userPool() });
    _pendingUser = user;
    user.authenticateUser(
      new AuthenticationDetails({ Username: username, Password: password }),
      {
        onSuccess: (session) => {
          _persistSession(session);
          resolve({ type: "DONE", idToken: session.getIdToken().getJwtToken() });
        },
        onFailure: (err) => reject(err),
        newPasswordRequired: (userAttributes) => {
          _pendingAttrs = userAttributes;
          resolve({ type: "NEW_PASSWORD_REQUIRED" });
        },
        totpRequired: () => resolve({ type: "SOFTWARE_TOKEN_MFA" }),
        mfaSetup: () => {
          user.associateSoftwareToken({
            onFailure: (err) => reject(err),
            associateSecretCode: (secretCode) =>
              resolve({ type: "MFA_SETUP", secretCode, username }),
          });
        },
      }
    );
  });
}

export function completeNewPasswordChallenge(newPassword: string): Promise<AuthChallenge> {
  return new Promise((resolve, reject) => {
    if (!_pendingUser) return reject(new Error("No sign-in in progress"));
    const cleanAttrs = { ..._pendingAttrs };
    delete (cleanAttrs as Record<string, unknown>).email_verified;
    delete (cleanAttrs as Record<string, unknown>).phone_number_verified;
    _pendingUser.completeNewPasswordChallenge(newPassword, cleanAttrs, {
      onSuccess: (session) => {
        _persistSession(session);
        resolve({ type: "DONE", idToken: session.getIdToken().getJwtToken() });
      },
      onFailure: (err) => reject(err),
      totpRequired: () => resolve({ type: "SOFTWARE_TOKEN_MFA" }),
      mfaSetup: () => {
        _pendingUser!.associateSoftwareToken({
          onFailure: (err) => reject(err),
          associateSecretCode: (secretCode) =>
            resolve({ type: "MFA_SETUP", secretCode, username: _pendingUser!.getUsername() }),
        });
      },
    });
  });
}

export function verifySoftwareToken(code: string): Promise<AuthChallenge> {
  return new Promise((resolve, reject) => {
    if (!_pendingUser) return reject(new Error("No sign-in in progress"));
    _pendingUser.verifySoftwareToken(code, "dashboard", {
      onSuccess: (session) => {
        _persistSession(session as unknown as CognitoUserSession);
        resolve({
          type: "DONE",
          idToken: (session as unknown as CognitoUserSession).getIdToken().getJwtToken(),
        });
      },
      onFailure: (err) => reject(err),
    });
  });
}

export function submitMfaCode(code: string): Promise<AuthChallenge> {
  return new Promise((resolve, reject) => {
    if (!_pendingUser) return reject(new Error("No sign-in in progress"));
    _pendingUser.sendMFACode(
      code,
      {
        onSuccess: (session) => {
          _persistSession(session);
          resolve({ type: "DONE", idToken: session.getIdToken().getJwtToken() });
        },
        onFailure: (err) => reject(err),
      },
      "SOFTWARE_TOKEN_MFA"
    );
  });
}

function _persistSession(session: CognitoUserSession) {
  sessionStorage.setItem(
    SESSION_STORAGE_KEY,
    JSON.stringify({
      idToken: session.getIdToken().getJwtToken(),
      refreshToken: session.getRefreshToken().getToken(),
      expiresAt: session.getIdToken().getExpiration() * 1000,
    })
  );
}

export function getIdToken(): string | null {
  const raw = sessionStorage.getItem(SESSION_STORAGE_KEY);
  if (!raw) return null;
  const { idToken, expiresAt } = JSON.parse(raw);
  if (Date.now() >= expiresAt) return null;
  return idToken;
}

export function hasValidSession(): boolean {
  return getIdToken() !== null;
}

export function signOut(): void {
  sessionStorage.removeItem(SESSION_STORAGE_KEY);
  const current = userPool().getCurrentUser();
  current?.signOut();
}
