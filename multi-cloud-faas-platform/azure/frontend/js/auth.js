import { config } from "./config.js";

/**
 * Get the ID token stored after Cognito login.
 * The ID token contains user profile claims such as email, name, and sub.
 */
export function getIdToken() {
  return sessionStorage.getItem("id_token");
}

/**
 * Get the access token stored after Cognito login.
 * The access token is used when calling protected backend APIs.
 */
export function getAccessToken() {
  return sessionStorage.getItem("access_token");
}

/**
 * Decode a JWT token payload.
 * Cognito tokens use base64url encoding, so the payload needs to be normalized
 * before using atob().
 */
export function decodeJwt(token) {
  const payload = token.split(".")[1];
  const normalizedPayload = payload.replace(/-/g, "+").replace(/_/g, "/");

  const paddedPayload = normalizedPayload.padEnd(
    normalizedPayload.length + (4 - normalizedPayload.length % 4) % 4,
    "="
  );

  return JSON.parse(atob(paddedPayload));
}

/**
 * Require the user to be logged in before accessing protected pages.
 * If the ID token is missing, invalid, or expired, the user is redirected
 * back to the landing/login page.
 */
export function requireLogin() {
  const idToken = getIdToken();

  if (!idToken) {
    window.location.href = "/";
    return null;
  }

  try {
    const claims = decodeJwt(idToken);

    // Check token expiry time. Cognito stores expiry as a Unix timestamp.
    const now = Math.floor(Date.now() / 1000);
    if (claims.exp && claims.exp < now) {
      sessionStorage.clear();
      window.location.href = "/";
      return null;
    }

    return claims;
  } catch (error) {
    console.error("Failed to read ID token:", error);

    // Clear any broken token data before redirecting the user.
    sessionStorage.clear();
    window.location.href = "/";
    return null;
  }
}

/**
 * Log the user out from both the local session and Cognito Hosted UI.
 */
export function logout() {
  sessionStorage.clear();

  const logoutUrl =
    `${config.cognitoDomain}/logout?` +
    `client_id=${config.clientId}` +
    `&logout_uri=${encodeURIComponent(config.logoutUri)}`;

  window.location.href = logoutUrl;
}