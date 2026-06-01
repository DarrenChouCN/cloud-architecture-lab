#!/usr/bin/env bash
set -euo pipefail

RESOURCE_GROUP="${1:-rg-multicloud-faas-dev}"
DEPLOYMENT_NAME="${2:-main}"
MODEL_DIR="${3:-azure/functions/wildlife-ml-worker/models}"

ROLE_NAME="Storage Blob Data Contributor"
MODEL_FILES=("mdv5a.pt" "model.pt")

echo "Using resource group: ${RESOURCE_GROUP}"
echo "Using deployment: ${DEPLOYMENT_NAME}"
echo "Using model directory: ${MODEL_DIR}"

az account show > /dev/null

echo "Reading deployment outputs..."

MODEL_STORAGE_ACCOUNT=$(az deployment group show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$DEPLOYMENT_NAME" \
  --query "properties.outputs.modelStorageAccountName.value" \
  -o tsv)

MODEL_CONTAINER=$(az deployment group show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$DEPLOYMENT_NAME" \
  --query "properties.outputs.modelContainerName.value" \
  -o tsv)

if [[ -z "$MODEL_STORAGE_ACCOUNT" || -z "$MODEL_CONTAINER" ]]; then
  echo "ERROR: Failed to read model storage outputs from deployment."
  exit 1
fi

echo "Model storage account: ${MODEL_STORAGE_ACCOUNT}"
echo "Model container: ${MODEL_CONTAINER}"

echo "Checking model files..."

for file_name in "${MODEL_FILES[@]}"; do
  file_path="${MODEL_DIR}/${file_name}"

  if [[ ! -f "$file_path" ]]; then
    echo "ERROR: Missing model file: ${file_path}"
    exit 1
  fi
done

echo "Reading current Azure user..."

USER_OBJECT_ID=$(az ad signed-in-user show \
  --query id \
  -o tsv)

STORAGE_ACCOUNT_ID=$(az storage account show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$MODEL_STORAGE_ACCOUNT" \
  --query id \
  -o tsv)

probe_blob_upload_permission() {
  local storage_account="$1"
  local container="$2"

  local probe_file
  probe_file="$(mktemp)"

  echo "rbac-probe" > "$probe_file"

  if az storage blob upload \
    --account-name "$storage_account" \
    --container-name "$container" \
    --name ".rbac-probe" \
    --file "$probe_file" \
    --auth-mode login \
    --overwrite \
    > /dev/null 2>&1; then

    az storage blob delete \
      --account-name "$storage_account" \
      --container-name "$container" \
      --name ".rbac-probe" \
      --auth-mode login \
      > /dev/null 2>&1 || true

    rm -f "$probe_file"
    return 0
  fi

  rm -f "$probe_file"
  return 1
}

wait_for_blob_permission() {
  local storage_account="$1"
  local container="$2"

  echo "Waiting for Blob data-plane permission to become effective..."

  for attempt in {1..30}; do
    if probe_blob_upload_permission "$storage_account" "$container"; then
      echo "Blob upload permission is ready."
      return 0
    fi

    echo "Permission not ready yet. Retry ${attempt}/30..."
    sleep 20
  done

  echo "ERROR: Blob upload permission did not become effective in time."
  exit 1
}

upload_blob_with_retry() {
  local storage_account="$1"
  local container="$2"
  local blob_name="$3"
  local file_path="$4"

  for attempt in {1..10}; do
    if az storage blob upload \
      --account-name "$storage_account" \
      --container-name "$container" \
      --name "$blob_name" \
      --file "$file_path" \
      --auth-mode login \
      --overwrite \
      > /dev/null; then

      echo "Uploaded ${blob_name}"
      return 0
    fi

    echo "Upload failed for ${blob_name}. Retry ${attempt}/10..."
    sleep 20
  done

  echo "ERROR: Failed to upload ${blob_name}"
  exit 1
}

echo "Checking Blob data-plane permission..."

if probe_blob_upload_permission "$MODEL_STORAGE_ACCOUNT" "$MODEL_CONTAINER"; then
  echo "Current user already has Blob upload permission."
else
  echo "Current user does not have Blob upload permission."
  echo "Checking role assignment: ${ROLE_NAME}"

  ROLE_ASSIGNMENT_COUNT=$(az role assignment list \
    --assignee "$USER_OBJECT_ID" \
    --role "$ROLE_NAME" \
    --scope "$STORAGE_ACCOUNT_ID" \
    --query "length(@)" \
    -o tsv)

  if [[ "$ROLE_ASSIGNMENT_COUNT" == "0" ]]; then
    echo "Assigning ${ROLE_NAME} to current user..."

    az role assignment create \
      --assignee "$USER_OBJECT_ID" \
      --assignee-principal-type User \
      --role "$ROLE_NAME" \
      --scope "$STORAGE_ACCOUNT_ID" \
      > /dev/null

    echo "Role assignment created."
  else
    echo "Required role assignment already exists, but data-plane permission is not ready yet."
  fi

  wait_for_blob_permission "$MODEL_STORAGE_ACCOUNT" "$MODEL_CONTAINER"
fi

echo "Uploading model artifacts..."

for file_name in "${MODEL_FILES[@]}"; do
  file_path="${MODEL_DIR}/${file_name}"
  upload_blob_with_retry "$MODEL_STORAGE_ACCOUNT" "$MODEL_CONTAINER" "$file_name" "$file_path"
done

echo "Verifying uploaded blobs..."

az storage blob list \
  --account-name "$MODEL_STORAGE_ACCOUNT" \
  --container-name "$MODEL_CONTAINER" \
  --auth-mode login \
  --query "[].{name:name,size:properties.contentLength}" \
  -o table

echo "Model artifact upload completed."