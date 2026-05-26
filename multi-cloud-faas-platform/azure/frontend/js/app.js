import { requireLogin, logout } from "./auth.js";
import { initUploadForm } from "./upload.js";
import { initMediaApiForm } from "./media_api.js";

function renderUserInfo(claims) {
  document.getElementById("email").textContent = claims.email || "";
  document.getElementById("givenName").textContent = claims.given_name || "";
  document.getElementById("familyName").textContent = claims.family_name || "";
  document.getElementById("sub").textContent = claims.sub || "";
}

function main() {
  const claims = requireLogin();

  if (!claims) {
    return;
  }

  renderUserInfo(claims);

  document.getElementById("status").textContent = "You are signed in with Cognito.";
  document.getElementById("userInfo").style.display = "block";
  document.getElementById("uploadSection").style.display = "block";
  document.getElementById("mediaApiSection").style.display = "block";

  document.getElementById("logoutButton").addEventListener("click", logout);

  initUploadForm();
  initMediaApiForm();
}

main();