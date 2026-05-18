import { config } from "./config.js";
import { getAccessToken } from "./auth.js";

async function calculateSha256(file) {
  const buffer = await file.arrayBuffer();
  const hashBuffer = await crypto.subtle.digest("SHA-256", buffer);

  return Array.from(new Uint8Array(hashBuffer))
    .map(byte => byte.toString(16).padStart(2, "0"))
    .join("");
}

async function requestUploadInit(file) {
  const accessToken = getAccessToken();

  if (!accessToken) {
    throw new Error("Missing access token. Please sign in again.");
  }

  const checksum = await calculateSha256(file);

  const response = await fetch(`${config.apiBaseUrl}/uploads/init`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${accessToken}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      filename: file.name,
      content_type: file.type,
      checksum: checksum,
      size: file.size
    })
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.message || "Failed to request upload URL.");
  }

  return data;
}

async function uploadFileToS3(file, uploadUrl) {
  const response = await fetch(uploadUrl, {
    method: "PUT",
    headers: {
      "Content-Type": file.type
    },
    body: file
  });

  if (!response.ok) {
    throw new Error("Failed to upload file to S3.");
  }
}

export function initUploadForm() {
  const fileInput = document.getElementById("fileInput");
  const uploadButton = document.getElementById("uploadButton");
  const uploadResult = document.getElementById("uploadResult");

  uploadButton.addEventListener("click", async () => {
    const file = fileInput.files[0];

    if (!file) {
      uploadResult.textContent = "Please select a file first.";
      return;
    }

    try {
      uploadButton.disabled = true;
      uploadResult.textContent = "Calculating checksum and requesting upload URL...";

      const uploadInitResult = await requestUploadInit(file);

      if (uploadInitResult.duplicated) {
        uploadResult.textContent =
          `File already exists.\n` +
          `File ID: ${uploadInitResult.file_id}\n` +
          `Object key: ${uploadInitResult.object_key}`;
        return;
      }

      uploadResult.textContent = "Uploading file to S3...";

      await uploadFileToS3(file, uploadInitResult.upload_url);

      uploadResult.textContent =
        `Upload completed.\n` +
        `File ID: ${uploadInitResult.file_id}\n` +
        `Object key: ${uploadInitResult.object_key}`;
    } catch (error) {
      console.error(error);
      uploadResult.textContent = error.message;
    } finally {
      uploadButton.disabled = false;
    }
  });
}