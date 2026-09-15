targetScope = 'resourceGroup'

@description('Short project name used to build consistent Azure resource names.')
param projectName string = 'multicloud-faas'

@description('Deployment environment.')
@allowed([
  'dev'
  'test'
  'prod'
])
param environmentName string = 'dev'

@description('Azure region for all regional resources.')
param location string = resourceGroup().location

@description('Deploy the ML worker after its image and model artifacts have been published.')
param deployMlWorker bool = false

@description('Container repository name inside Azure Container Registry.')
param imageRepository string = 'wildlife-ml-worker'

@description('Container image tag to deploy.')
param imageTag string = 'latest'

@description('Blob container that stores the ML model artifacts.')
param modelContainerName string = 'models'

@description('Model version reported by the ML worker.')
param modelVersion string = 'v1'

@description('ML worker CPU cores.')
param cpu int = 2

@description('ML worker memory allocation.')
param memory string = '4Gi'

@description('Minimum ML worker replicas. Keep one warm to avoid model-download cold starts during demos.')
param minReplicas int = 1

@description('Maximum ML worker replicas.')
param maxReplicas int = 1

var projectToken = toLower(replace(projectName, '-', ''))
var resourceSuffix = uniqueString(subscription().subscriptionId, resourceGroup().id, projectName, environmentName)
var commonTags = {
  project: projectName
  environment: environmentName
  managedBy: 'Bicep'
}

// Globally unique resources cannot contain hyphens. The suffix is deterministic
// for this subscription, resource group, project, and environment.
var acrName = take('cr${projectToken}${environmentName}${resourceSuffix}', 50)
var modelStorageAccountName = take('st${take(projectToken, 6)}${environmentName}${take(resourceSuffix, 10)}', 24)

var staticWebAppName = 'swa-${projectName}-${environmentName}'
var logAnalyticsWorkspaceName = 'log-${projectName}-${environmentName}'
var containerAppEnvironmentName = 'cae-${projectName}-${environmentName}'
var mlWorkerIdentityName = 'id-${projectName}-ml-${environmentName}'
var mlWorkerResourceName = 'ca-${projectName}-ml-${environmentName}'

// Azure built-in role: AcrPull.
var acrPullRoleDefinitionId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource staticWebApp 'Microsoft.Web/staticSites@2025-03-01' = {
  name: staticWebAppName
  location: 'eastasia'
  tags: commonTags
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {}
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  tags: commonTags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource modelStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: modelStorageAccountName
  location: location
  tags: commonTags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: true
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: modelStorage
  name: 'default'
}

resource modelContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: modelContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsWorkspaceName
  location: location
  tags: commonTags
  properties: {
    retentionInDays: 30
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
    sku: {
      name: 'PerGB2018'
    }
  }
}

resource containerAppEnvironment 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: containerAppEnvironmentName
  location: location
  tags: commonTags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsWorkspace.properties.customerId
        sharedKey: logAnalyticsWorkspace.listKeys().primarySharedKey
      }
    }
    zoneRedundant: false
  }
}

resource mlWorkerIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: mlWorkerIdentityName
  location: location
  tags: commonTags
}

resource acrPullRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, mlWorkerIdentity.id, acrPullRoleDefinitionId)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleDefinitionId)
    principalId: mlWorkerIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// The worker is deliberately conditional. On a new environment, publish the two
// model artifacts and the container image after the platform deployment, then
// rerun this template with deployMlWorker=true.
resource mlWorkerApp 'Microsoft.App/containerApps@2023-05-01' = if (deployMlWorker) {
  name: mlWorkerResourceName
  location: location
  tags: commonTags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${mlWorkerIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerAppEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: acr.properties.loginServer
          identity: mlWorkerIdentity.id
        }
      ]
      secrets: [
        {
          name: 'model-storage-key'
          value: modelStorage.listKeys().keys[0].value
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'wildlife-ml-worker'
          image: '${acr.properties.loginServer}/${imageRepository}:${imageTag}'
          resources: {
            cpu: cpu
            memory: memory
          }
          env: [
            {
              name: 'MODEL_STORAGE_ACCOUNT'
              value: modelStorage.name
            }
            {
              name: 'MODEL_CONTAINER'
              value: modelContainer.name
            }
            {
              name: 'MODEL_STORAGE_KEY'
              secretRef: 'model-storage-key'
            }
            {
              name: 'MODEL_VERSION'
              value: modelVersion
            }
            {
              name: 'PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION'
              value: 'python'
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
    }
  }
  dependsOn: [
    acrPullRoleAssignment
  ]
}

output staticWebAppName string = staticWebApp.name
output staticWebAppHostname string = staticWebApp.properties.defaultHostname
output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output modelStorageAccountName string = modelStorage.name
output modelContainerName string = modelContainer.name
output containerAppEnvironmentName string = containerAppEnvironment.name
output mlWorkerIdentityName string = mlWorkerIdentity.name
output mlWorkerAppName string = mlWorkerResourceName
output mlWorkerFqdn string = mlWorkerApp.?properties.configuration.ingress.fqdn ?? ''
output mlWorkerBaseUrl string = deployMlWorker ? 'https://${mlWorkerApp!.properties.configuration.ingress.fqdn}' : ''
