import { config } from "./config.js";
import { getAccessToken } from "./auth.js";

/**
 * Send an authenticated request to the backend API Gateway.
 * All protected API calls include the Cognito access token in the Authorization header.
 */
async function callApi(path, options = {}) {
  const accessToken = getAccessToken();

  if (!accessToken) {
    throw new Error("Missing access token. Please sign in again.");
  }

  const response = await fetch(`${config.apiBaseUrl}${path}`, {
    ...options,
    headers: {
      "Authorization": `Bearer ${accessToken}`,
      "Content-Type": "application/json",
      ...(options.headers || {})
    }
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.message || "API request failed.");
  }

  return data;
}

/**
 * Display API response data in a readable JSON format.
 */
function showResult(elementId, data) {
  document.getElementById(elementId).textContent = JSON.stringify(data, null, 2);
}

/**
 * Extract media records from different possible backend response formats.
 * Current query-by-file response uses matched_files.
 */
function getResultItems(data) {
  if (Array.isArray(data)) {
    return data;
  }

  return data.matched_files || data.items || data.results || data.files || data.media || [];
}

/**
 * Format tags for display in preview cards.
 */
function formatTagsForCard(tags) {
  if (!tags || Object.keys(tags).length === 0) {
    return "No tags";
  }

  return Object.entries(tags)
    .map(([tag, count]) => `${tag}: ${count}`)
    .join(", ");
}

/**
 * Render thumbnail previews for image results and clickable links for videos.
 * For images, thumbnail_url is displayed and original_url is opened when clicked.
 */
function renderMediaPreview(elementId, data) {
  const container = document.getElementById(elementId);

  if (!container) {
    return;
  }

  const items = getResultItems(data);
  container.innerHTML = "";

  if (!items.length) {
    container.textContent = "No preview items found.";
    return;
  }

  items.forEach(item => {
    const card = document.createElement("div");
    card.className = "media-card";

    const fileType = item.file_type || item.type;
    const thumbnailUrl = item.thumbnail_url || item.thumbnailUrl || item.url;
    const originalUrl = item.original_url || item.originalUrl || item.file_url || item.url;
    const videoUrl = item.video_url || item.file_url || item.original_url || item.url;

    if (fileType === "image" && thumbnailUrl) {
      const link = document.createElement("a");
      link.href = originalUrl || thumbnailUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.title = "Open full-size image";

      const img = document.createElement("img");
      img.src = thumbnailUrl;
      img.alt = "Image thumbnail";

      link.appendChild(img);
      card.appendChild(link);

      const caption = document.createElement("p");
      caption.textContent = "Click thumbnail to open full-size image.";
      card.appendChild(caption);
    } else if (fileType === "video" && videoUrl) {
      const link = document.createElement("a");
      link.href = videoUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "Open video";
      card.appendChild(link);
    } else {
      const link = document.createElement("a");
      link.href = originalUrl || thumbnailUrl || videoUrl || "#";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "Open file";
      card.appendChild(link);
    }

    if (item.tags) {
      const tagText = document.createElement("p");
      tagText.className = "media-tags";
      tagText.textContent = `Tags: ${formatTagsForCard(item.tags)}`;
      card.appendChild(tagText);
    }

    if (item.file_id) {
      const fileId = document.createElement("p");
      fileId.className = "media-file-id";
      fileId.textContent = `File ID: ${item.file_id}`;
      card.appendChild(fileId);
    }

    container.appendChild(card);
  });
}

/**
 * Read multiple lines from a textarea and remove empty lines.
 * This is used for bulk operations where users provide multiple URLs or object keys.
 */
function readLines(elementId) {
  return document
    .getElementById(elementId)
    .value
    .split("\n")
    .map(value => value.trim())
    .filter(Boolean);
}

/**
 * Read comma-separated values from an input field.
 * This is used for entering multiple tags.
 */
function readCsv(elementId) {
  return document
    .getElementById(elementId)
    .value
    .split(",")
    .map(value => value.trim())
    .filter(Boolean);
}

/**
 * Convert a selected local file into a data URL.
 * The query-by-file API sends this encoded file content to the backend.
 */
function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();

    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("Failed to read query file."));

    reader.readAsDataURL(file);
  });
}

/**
 * Infer whether the uploaded query file is an image or video based on MIME type.
 */
function inferFileType(file) {
  if (file.type.startsWith("image/")) {
    return "image";
  }

  if (file.type.startsWith("video/")) {
    return "video";
  }

  throw new Error("Query file must be an image or video.");
}

/**
 * Query stored media by tag counts.
 * Example input: {"koala": 2, "wombat": 1}
 */
function initQueryTags() {
  document.getElementById("queryTagsButton").addEventListener("click", async () => {
    try {
      const tags = JSON.parse(document.getElementById("queryTagsInput").value || "{}");

      const result = await callApi("/query/tags", {
        method: "POST",
        body: JSON.stringify({ tags })
      });

      showResult("queryTagsResult", result);
      renderMediaPreview("queryTagsPreview", result);
    } catch (error) {
      showResult("queryTagsResult", { error: error.message });
      renderMediaPreview("queryTagsPreview", { matched_files: [] });
    }
  });
}

/**
 * Query stored media by a single species name.
 */
function initQuerySpecies() {
  document.getElementById("querySpeciesButton").addEventListener("click", async () => {
    try {
      const species = document.getElementById("querySpeciesInput").value.trim();

      if (!species) {
        throw new Error("Please enter a species name.");
      }

      const result = await callApi(`/query/species?species=${encodeURIComponent(species)}`, {
        method: "GET"
      });

      showResult("querySpeciesResult", result);
      renderMediaPreview("querySpeciesPreview", result);
    } catch (error) {
      showResult("querySpeciesResult", { error: error.message });
      renderMediaPreview("querySpeciesPreview", { matched_files: [] });
    }
  });
}

/**
 * Query media by uploading a temporary image or video file.
 * The file is encoded and sent to the backend. The backend then calls the Azure
 * ML worker to extract tags and uses those tags to search existing media records.
 */
function initQueryByFile() {
  document.getElementById("queryByFileButton").addEventListener("click", async () => {
    const fileInput = document.getElementById("queryByFileInput");
    const button = document.getElementById("queryByFileButton");
    const status = document.getElementById("queryByFileStatus");

    try {
      const file = fileInput.files[0];

      if (!file) {
        throw new Error("Please select a query file first.");
      }

      button.disabled = true;
      status.textContent = "Preparing query file...";
      showResult("queryByFileResult", {});
      renderMediaPreview("queryByFilePreview", { matched_files: [] });

      const dataBase64 = await readFileAsDataUrl(file);
      const fileType = inferFileType(file);

      status.textContent =
        "Uploading and analyzing query file with Azure ML. This may take a few seconds...";

      const result = await callApi("/query/by-file", {
        method: "POST",
        body: JSON.stringify({
          filename: file.name,
          content_type: file.type,
          file_type: fileType,
          data_base64: dataBase64
        })
      });

      status.textContent = "Query completed.";
      showResult("queryByFileResult", result);
      renderMediaPreview("queryByFilePreview", result);
    } catch (error) {
      console.error(error);
      status.textContent = "Query failed.";
      showResult("queryByFileResult", { error: error.message });
      renderMediaPreview("queryByFilePreview", { matched_files: [] });
    } finally {
      button.disabled = false;
    }
  });
}

/**
 * Find the original full-size image from a thumbnail URL or object key.
 */
function initQueryThumbnail() {
  document.getElementById("queryThumbnailButton").addEventListener("click", async () => {
    try {
      const thumbnailUrl = document.getElementById("queryThumbnailInput").value.trim();

      if (!thumbnailUrl) {
        throw new Error("Please enter a thumbnail URL or object key.");
      }

      const result = await callApi("/query/thumbnail", {
        method: "POST",
        body: JSON.stringify({
          thumbnail_url: thumbnailUrl
        })
      });

      showResult("queryThumbnailResult", result);
    } catch (error) {
      showResult("queryThumbnailResult", { error: error.message });
    }
  });
}

/**
 * Add or remove tags from multiple media records.
 * operation = add means add tags, operation = remove means remove tags.
 */
function initBulkTags() {
  document.getElementById("bulkTagsButton").addEventListener("click", async () => {
    try {
      const urls = readLines("bulkUrlsInput");
      const tags = readCsv("bulkTagsInput");
      const operation = document.getElementById("bulkOperationInput").value;

      if (!urls.length) {
        throw new Error("Please enter at least one file URL or object key.");
      }

      if (!tags.length) {
        throw new Error("Please enter at least one tag.");
      }

      const result = await callApi("/tags/bulk", {
        method: "POST",
        body: JSON.stringify({
          urls,
          tags,
          operation
        })
      });

      showResult("bulkTagsResult", result);
    } catch (error) {
      showResult("bulkTagsResult", { error: error.message });
    }
  });
}

/**
 * Delete media files and their related metadata.
 * The backend is responsible for deleting S3 objects and DynamoDB records.
 */
function initDeleteFiles() {
  document.getElementById("deleteFilesButton").addEventListener("click", async () => {
    try {
      const urls = readLines("deleteUrlsInput");

      if (!urls.length) {
        throw new Error("Please enter at least one file URL or object key.");
      }

      const confirmed = window.confirm(
        "This will delete S3 objects and DynamoDB metadata. Continue?"
      );

      if (!confirmed) {
        return;
      }

      const result = await callApi("/files/delete", {
        method: "POST",
        body: JSON.stringify({
          urls
        })
      });

      showResult("deleteFilesResult", result);
    } catch (error) {
      showResult("deleteFilesResult", { error: error.message });
    }
  });
}

/**
 * Initialize all media API forms on the protected application page.
 */
export function initMediaApiForm() {
  initQueryTags();
  initQuerySpecies();
  initQueryByFile();
  initQueryThumbnail();
  initBulkTags();
  initDeleteFiles();
}
