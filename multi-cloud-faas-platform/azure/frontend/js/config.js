/**
 * Frontend configuration for Cognito authentication and backend API access.
 *
 * These values connect the Azure Static Web App frontend with AWS Cognito
 * and Amazon API Gateway. They are not secret keys, but they should still be
 * kept consistent with the deployed cloud resources.
 */
export const config = {
  // Cognito Hosted UI domain used for login and logout.
  cognitoDomain: "https://shaomin-faas-dev.auth.us-east-1.amazoncognito.com",

  // Cognito App Client ID used by the frontend authentication flow.
  clientId: "2ffrs1pe6rlkb6jf2mpopbqhfq",

  // URL that Cognito redirects to after successful login.
  redirectUri: "https://blue-wave-0c8589a0f.7.azurestaticapps.net/callback",

  // URL that Cognito redirects to after logout.
  logoutUri: "https://blue-wave-0c8589a0f.7.azurestaticapps.net/",

  // Main application page shown after login.
  appUrl: "/app.html",

  // Amazon API Gateway base URL for protected backend API calls.
  apiBaseUrl: "https://3iggcqp0h4.execute-api.us-east-1.amazonaws.com"
};