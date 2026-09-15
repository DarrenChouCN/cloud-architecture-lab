targetScope = 'subscription'

param projectName string = 'multicloud-faas'

@allowed([
  'dev'
  'test'
  'prod'
])
param environmentName string = 'dev'

param location string = 'australiaeast'

// Set to true after uploading both model files and pushing the container image to ACR.
param deployMlWorker bool = false

param imageRepository string = 'wildlife-ml-worker'
param imageTag string = 'latest'
param modelContainerName string = 'models'
param modelVersion string = 'v1'
param cpu int = 2
param memory string = '4Gi'
param minReplicas int = 1
param maxReplicas int = 1

resource projectResourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${projectName}-${environmentName}'
  location: location
  tags: {
    project: projectName
    environment: environmentName
    managedBy: 'Bicep'
  }
}

module platform './resources.bicep' = {
  // The model upload script reads this resource-group deployment's outputs.
  name: 'main'
  scope: projectResourceGroup
  params: {
    projectName: projectName
    environmentName: environmentName
    location: location
    deployMlWorker: deployMlWorker
    imageRepository: imageRepository
    imageTag: imageTag
    modelContainerName: modelContainerName
    modelVersion: modelVersion
    cpu: cpu
    memory: memory
    minReplicas: minReplicas
    maxReplicas: maxReplicas
  }
}

output resourceGroupName string = projectResourceGroup.name
output staticWebAppName string = platform.outputs.staticWebAppName
output staticWebAppHostname string = platform.outputs.staticWebAppHostname
output acrName string = platform.outputs.acrName
output acrLoginServer string = platform.outputs.acrLoginServer
output modelStorageAccountName string = platform.outputs.modelStorageAccountName
output modelContainerName string = platform.outputs.modelContainerName
output containerAppEnvironmentName string = platform.outputs.containerAppEnvironmentName
output mlWorkerIdentityName string = platform.outputs.mlWorkerIdentityName
output mlWorkerAppName string = platform.outputs.mlWorkerAppName
output mlWorkerFqdn string = platform.outputs.mlWorkerFqdn
output mlWorkerBaseUrl string = platform.outputs.mlWorkerBaseUrl
