## Deploy Azure Infrastructure

Provision the resource group, ACR, model storage, Container Apps environment, Log Analytics, and Static Web App with Bicep. A user-assigned managed identity grants the ML worker permission to pull images from ACR.

See [main.bicep](multi-cloud-faas-platform/azure/infra/main.bicep), [resources.bicep](multi-cloud-faas-platform/azure/infra/resources.bicep), and [deployment parameters](multi-cloud-faas-platform/azure/infra/dev.bicepparam).

```bash
# From the repository root
cd multi-cloud-faas-platform

# Confirm the active subscription
az account show --query '{name:name,id:id}' -o table
export subscription_id="$(az account show --query id -o tsv)"

# Deploy the resource group and supporting infrastructure
az deployment sub create \
  --subscription "$subscription_id" \
  --name multicloud-faas-dev \
  --location australiaeast \
  --template-file azure/infra/main.bicep \
  --parameters azure/infra/dev.bicepparam
```

- Keep `deployMlWorker = false` for the initial deployment. Deploy the ML worker after publishing its container image and uploading `mdv5a.pt` and `model.pt`.
- Regional resources use `australiaeast`. Static Web Apps uses `eastasia` because its supported deployment regions differ.
- Models are stored in a private Blob container and downloaded at application startup, independently of the Docker image.
- In production, Azure DevOps pipelines can provision infrastructure with Bicep, build and push images to ACR, and deploy applications to Azure Container Apps. This lab runs these steps manually to demonstrate the same deployment flow.

```bash
# Verify deployment status and provisioned resources
az deployment sub show --subscription "$subscription_id" --name multicloud-faas-dev --query properties.provisioningState -o tsv

az resource list --subscription "$subscription_id" --resource-group rg-multicloud-faas-dev -o table
```

Deployment completed successfully:

![Azure infrastructure deployment](images/azure-infra-deployment.png)

Provisioned Azure resources:

![Azure resource group overview](images/azure-infra-resources.png)

## Publish ML Model Artifacts

Model artifacts are managed separately from the inference container image. This allows models to be updated without rebuilding the application image, at the cost of downloading them when a new container starts.

Place `mdv5a.pt` and `model.pt` in `azure/src/ml-worker/models/`, then run from the `multi-cloud-faas-platform/` directory:

```bash
bash azure/src/ml-worker/script/upload-models.sh
```

In production, ML pipelines typically publish versioned models to a model registry for inference services to retrieve. This lab uses a local script and Blob Storage to simulate artifact publishing and startup retrieval; model registration and version promotion are outside its scope.

See [model upload script](multi-cloud-faas-platform/azure/src/ml-worker/script/upload-models.sh).

Upload logs:

![Model upload logs](images/azure-model-upload-cli.png)

Both model artifacts in the Azure Blob Storage `models` container:

![Model artifacts in Azure Blob Storage](images/azure-model-artifacts-portal.png)

## Build and Push the ML Worker Image

Build the ML worker image and push it to ACR before deploying it to Azure Container Apps.

Run the following commands from the `multi-cloud-faas-platform/` directory:

```bash
# Read the registry details from Bicep deployment outputs
RESOURCE_GROUP="rg-multicloud-faas-dev"
DEPLOYMENT_NAME="main"

ACR_NAME=$(az deployment group show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$DEPLOYMENT_NAME" \
  --query "properties.outputs.acrName.value" -o tsv)

ACR_SERVER=$(az deployment group show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$DEPLOYMENT_NAME" \
  --query "properties.outputs.acrLoginServer.value" -o tsv)

# Log in to ACR
az acr login --name "$ACR_NAME"

# Build the ML worker image
docker build --platform linux/amd64 \
  -t "$ACR_SERVER/wildlife-ml-worker:latest" \
  azure/src/ml-worker/

# Push the image to ACR
docker push "$ACR_SERVER/wildlife-ml-worker:latest"

# Verify the published image tag
az acr repository show-tags \
  --name "$ACR_NAME" \
  --repository wildlife-ml-worker \
  --query "[].{Image: join('', ['${ACR_SERVER}/wildlife-ml-worker:', @])}" \
  -o table
```

In production, CI/CD pipelines, such as Azure Pipelines, build and push images to ACR and deploy them to Azure Container Apps. This lab builds and pushes the image manually, then deploys it using Bicep.

See [application source and Dockerfile](multi-cloud-faas-platform/azure/src/ml-worker/).

The image uses the `latest` tag configured in the Bicep deployment parameters. Model files are downloaded at startup and are excluded from the image.

![ML worker image build and size](images/azure-ml-worker-image-build.png)

![ML worker image pushed to ACR](images/azure-ml-worker-image-push.png)

## Deploy the ML Worker to Azure Container Apps

Deploy the published image from ACR. The container downloads the model artifacts from Blob Storage during startup.

In production, CI/CD pipelines typically deploy container images to Azure Container Apps. This lab runs the Bicep deployment manually to demonstrate the same deployment step.

See [Container App configuration](multi-cloud-faas-platform/azure/infra/resources.bicep) and [deployment parameters](multi-cloud-faas-platform/azure/infra/dev.bicepparam).

After publishing the image and both model files, update `azure/infra/dev.bicepparam`:

```bicep
// Deploy the ML worker after publishing its image and model artifacts.
param deployMlWorker = true
```

Run from the `multi-cloud-faas-platform/` directory:

```bash
export subscription_id="$(az account show --query id -o tsv)"
RESOURCE_GROUP="rg-multicloud-faas-dev"
CONTAINER_APP="ca-multicloud-faas-ml-dev"

# Deploy the ML worker using the existing infrastructure
az deployment sub create \
  --subscription "$subscription_id" \
  --name multicloud-faas-dev \
  --location australiaeast \
  --template-file azure/infra/main.bicep \
  --parameters azure/infra/dev.bicepparam \
  --query "properties.provisioningState" \
  -o tsv

# Verify the deployed image and application status
az containerapp show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$CONTAINER_APP" \
  --query "{Name:name,Provisioning:properties.provisioningState,Running:properties.runningStatus,Image:properties.template.containers[0].image}" \
  -o table

# Retrieve the application endpoint
ACA_FQDN=$(az containerapp show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$CONTAINER_APP" \
  --query "properties.configuration.ingress.fqdn" \
  -o tsv)

export ACA_BASE_URL="https://${ACA_FQDN}"

# Verify HTTPS access and startup readiness
echo "$ACA_BASE_URL"
curl --fail-with-body --show-error "${ACA_BASE_URL}/health"
echo
```

The health endpoint should return `"status": "ok"` and `"model_files_ready": true`. This confirms startup readiness; model loading and inference are verified separately with a real image.

Deployment and endpoint verification:

![ACA deployment and health verification](images/azure-ml-worker-deployment-health.png)

Container App details in the Azure portal:

![ML worker running in Azure Container Apps](images/azure-ml-worker-portal.png)

## Connect AWS Lambda to the Azure ML Worker

Use the deployed Container App's Application URL as the base address for AWS-to-Azure inference requests:

```text
https://ca-multicloud-faas-ml-dev.ambitiousisland-db4bf688.australiaeast.azurecontainerapps.io
```

Update the endpoint parameter defaults in the following SAM templates.

In [storage/template.yaml](multi-cloud-faas-platform/aws/infra/storage/template.yaml):

```yaml
  AzureImageProcessingEndpoint:
    Type: String
    Default: "https://ca-multicloud-faas-ml-dev.ambitiousisland-db4bf688.australiaeast.azurecontainerapps.io/process-image"
    Description: Azure Container Apps endpoint for image processing.

  AzureVideoProcessingEndpoint:
    Type: String
    Default: "https://ca-multicloud-faas-ml-dev.ambitiousisland-db4bf688.australiaeast.azurecontainerapps.io/process-video"
    Description: Azure Container Apps endpoint for video processing.
```

In [api/template.yaml](multi-cloud-faas-platform/aws/infra/api/template.yaml):

```yaml
  QueryFileAnalysisEndpoint:
    Type: String
    Default: "https://ca-multicloud-faas-ml-dev.ambitiousisland-db4bf688.australiaeast.azurecontainerapps.io/analyze-query-file"
    Description: Azure Container Apps endpoint for query-file analysis.
```

Commit and push these changes to trigger the AWS deployment pipeline. SAM passes the endpoint values into the Lambda environment variables.

This connects the two clouds: AWS Lambda sends HTTPS inference requests containing temporary S3 presigned URLs; the Azure ML worker retrieves the media and returns inference results. Model artifacts remain in Azure Blob Storage.

In production, service endpoints are typically managed as environment-specific configuration, for example in AWS Systems Manager Parameter Store, and injected into Lambda environment variables during deployment. This lab keeps the URLs in SAM parameter defaults for simplicity; the application code reads them from environment variables.