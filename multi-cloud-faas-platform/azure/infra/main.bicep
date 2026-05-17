targetScope = 'resourceGroup'

param staticWebAppName string = 'swa-multicloud-faas-dev'
param location string = 'eastus2'

resource staticWebApp 'Microsoft.Web/staticSites@2025-03-01' = {
  name: staticWebAppName
  location: location
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {}
}
