targetScope = 'resourceGroup'

param environmentName string = 'dev'
param location string = resourceGroup().location

param staticWebAppName string

module staticWebApp './modules/static-web-app.bicep' = {
  name: 'static-web-app-${environmentName}'
  params: {
    name: staticWebAppName
    location: location
  }
}
