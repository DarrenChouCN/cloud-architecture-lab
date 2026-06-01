@description('Azure region')
param location string = resourceGroup().location

@description('Container App name')
param appName string = 'wildlife-ml-worker'

@description('Existing Container Apps Environment name')
param containerAppEnvName string = 'fit5225-ml-env'

@description('Existing Azure Container Registry name')
param acrName string = 'fit5225mlacr001'

@description('Container image to deploy')
param imageName string = 'fit5225mlacr001.azurecr.io/wildlife-ml-worker:latest'

@description('Existing model storage account name')
param modelStorageAccountName string = 'fit5225mlmodelyl001'

@description('Model blob container name')
param modelContainerName string = 'models'

@description('Model version')
param modelVersion string = 'v1'

@description('Container CPU cores')
param cpu int = 2

@description('Container memory')
param memory string = '4Gi'

@description('Minimum replicas. Use 1 for demo to avoid cold start model download.')
param minReplicas int = 1

@description('Maximum replicas')
param maxReplicas int = 1

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
}

resource modelStorage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: modelStorageAccountName
}

resource containerAppEnv 'Microsoft.App/managedEnvironments@2023-05-01' existing = {
  name: containerAppEnvName
}

var acrCredentials = acr.listCredentials()
var acrUsername = acrCredentials.username
var acrPassword = acrCredentials.passwords[0].value

var modelStorageKey = modelStorage.listKeys().keys[0].value

resource mlWorkerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: appName
  location: location

  properties: {
    managedEnvironmentId: containerAppEnv.id

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
          server: '${acrName}.azurecr.io'
          username: acrUsername
          passwordSecretRef: 'acr-password'
        }
      ]

      secrets: [
        {
          name: 'acr-password'
          value: acrPassword
        }
        {
          name: 'model-storage-key'
          value: modelStorageKey
        }
      ]
    }

    template: {
      containers: [
        {
          name: 'wildlife-ml-worker'
          image: imageName

          resources: {
            cpu: cpu
            memory: memory
          }

          env: [
            {
              name: 'MODEL_STORAGE_ACCOUNT'
              value: modelStorageAccountName
            }
            {
              name: 'MODEL_CONTAINER'
              value: modelContainerName
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
}

output appFqdn string = mlWorkerApp.properties.configuration.ingress.fqdn
output baseUrl string = 'https://${mlWorkerApp.properties.configuration.ingress.fqdn}'