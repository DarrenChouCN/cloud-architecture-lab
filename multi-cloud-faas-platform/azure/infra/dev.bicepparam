using './main.bicep'

param location = 'australiaeast'

param projectName = 'multicloud-faas'
param environmentName = 'dev'
param imageRepository = 'wildlife-ml-worker'
param imageTag = 'latest'
param modelContainerName = 'models'
param modelVersion = 'v1'
param cpu = 2
param memory = '4Gi'
param minReplicas = 1
param maxReplicas = 1

// Set to true after uploading both model files and pushing the container image to ACR.
param deployMlWorker = false
