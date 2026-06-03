import { config } from "./config.js";
import { getAccessToken } from "./auth.js";

/**
 * Calculate the SHA-256 checksum of a selected file in the browser.
 * The checksum is sent to the backend so duplicate uploads can be detected
 * before the file is stored in S3.
 */
async function calculateSha256(file) {
  const buffer = await file.arrayBuffer();
  const hashBuffer = await crypto.subtle.digest("SHA-256", buffer);

  return Array.from(new Uint8Array(hashBuffer))
    .map(byte => byte.toString(16).padStart(2, "0"))
    .join("");
}

function formatTags(tags) {
  if (!tags || Object.keys(tags).length === 0) {
    return "No species tags available yet.";
  }

  return Object.entries(tags)
    .map(([species, count]) => `- ${species}: ${count}`)
    .join("\n");
}

/**
 * Ask the backend to initialise an upload.
 * The backend checks the checksum and returns either a duplicated result
 * or a presigned S3 upload URL for a new file.
 */
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

/**
 * Upload the selected file directly to S3 using the presigned URL returned
 * by the backend. The frontend does not need AWS credentials for this step.
 */
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

/**
 * Initialise the upload form on the protected application page.
 * This handles checksum calculation, duplicate checking, presigned URL upload,
 * and status messages shown to the user.
 */
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

      // If the backend detects a duplicate checksum, skip the S3 upload step.
      if (uploadInitResult.duplicated) {
        uploadResult.textContent =
          `File already exists.\n` +
          `File ID: ${uploadInitResult.file_id}\n` +
          `Object key: ${uploadInitResult.object_key}\n` +
          `Status: ${uploadInitResult.status || "unknown"}\n\n` +
          `Detected species:\n` +
          formatTags(uploadInitResult.tags);
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