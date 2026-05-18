import { config } from "./config.js";

export function getIdToken() {
  return sessionStorage.getItem("id_token");
}

export function getAccessToken() {
  return sessionStorage.getItem("access_token");
}

export function decodeJwt(token) {
  const payload = token.split(".")[1];
  const normalizedPayload = payload.replace(/-/g, "+").replace(/_/g, "/");

  const paddedPayload = normalizedPayload.padEnd(
    normalizedPayload.length + (4 - normalizedPayload.length % 4) % 4,
    "="
  );

  return JSON.parse(atob(paddedPayload));
}

export function requireLogin() {
  const idToken = getIdToken();

  if (!idToken) {
    window.location.href = "/";
    return null;
  }

  try {
    const claims = decodeJwt(idToken);

    const now = Math.floor(Date.now() / 1000);
    if (claims.exp && claims.exp < now) {
      sessionStorage.clear();
      window.location.href = "/";
      return null;
    }

    return claims;
  } catch (error) {
    console.error("Failed to read ID token:", error);
    sessionStorage.clear();
    window.location.href = "/";
    return null;
  }
}

export function logout() {
  sessionStorage.clear();

  const logoutUrl =
    `${config.cognitoDomain}/logout?` +
    `client_id=${config.clientId}` +
    `&logout_uri=${encodeURIComponent(config.logoutUri)}`;

  window.location.href = logoutUrl;
}