## Deploy Azure Infrastructure

Provision the resource group, ACR, model storage, Container Apps environment, Log Analytics, and Static Web App with Bicep. A user-assigned managed identity grants the ML worker permission to pull images from ACR.

See [main.bicep](azure/infra/main.bicep), [resources.bicep](azure/infra/resources.bicep), and [deployment parameters](azure/infra/dev.bicepparam).

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