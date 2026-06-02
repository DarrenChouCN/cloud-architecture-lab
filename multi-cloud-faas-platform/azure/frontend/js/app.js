import { requireLogin, logout } from "./auth.js";
import { initUploadForm } from "./upload.js";
import { initMediaApiForm } from "./media_api.js";

/**
 * Render basic Cognito user information on the page.
 * The claims are decoded from the user's JWT token after login.
 */
function renderUserInfo(claims) {
  document.getElementById("email").textContent = claims.email || "";
  document.getElementById("givenName").textContent = claims.given_name || "";
  document.getElementById("familyName").textContent = claims.family_name || "";
  document.getElementById("sub").textContent = claims.sub || "";
}

/**
 * Main entry point of the frontend application.
 * It checks whether the user is logged in, shows protected sections,
 * and initializes the upload and media management forms.
 */
function main() {
  // Redirect unauthenticated users and return the Cognito claims for signed-in users.
  const claims = requireLogin();

  if (!claims) {
    return;
  }

  // Display the signed-in user's Cognito profile information.
  renderUserInfo(claims);

  // Show protected application sections after successful authentication.
  document.getElementById("status").textContent = "You are signed in with Cognito.";
  document.getElementById("userInfo").style.display = "block";
  document.getElementById("uploadSection").style.display = "block";
  document.getElementById("mediaApiSection").style.display = "block";

  // Bind logout action to the logout button.
  document.getElementById("logoutButton").addEventListener("click", logout);

  // Initialize upload workflow and media query/update/delete API forms.
  initUploadForm();
  initMediaApiForm();
}

main();

