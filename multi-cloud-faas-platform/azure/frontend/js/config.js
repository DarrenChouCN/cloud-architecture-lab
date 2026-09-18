export const config = {
  // Cognito Hosted UI for the deployed AWS environment.
  cognitoDomain:
    "https://darren-faas-dev-246766637759.auth.ap-southeast-2.amazoncognito.com",

  clientId: "4nfmtovob4c6pkph95dkvpih43",

  // The deployed origin must also be registered in Cognito.
  redirectUri: `${window.location.origin}/callback`,
  logoutUri: `${window.location.origin}/`,

  appUrl: "/app.html",

  apiBaseUrl:
    "https://p25vw507ok.execute-api.ap-southeast-2.amazonaws.com"
};