import { config } from "./config.js";
import { getAccessToken } from "./auth.js";

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

function showResult(elementId, data) {
  document.getElementById(elementId).textContent = JSON.stringify(data, null, 2);
}

function readLines(elementId) {
  return document
    .getElementById(elementId)
    .value
    .split("\n")
    .map(value => value.trim())
    .filter(Boolean);
}

function readCsv(elementId) {
  return document
    .getElementById(elementId)
    .value
    .split(",")
    .map(value => value.trim())
    .filter(Boolean);
}

function initQueryTags() {
  document.getElementById("queryTagsButton").addEventListener("click", async () => {
    try {
      const tags = JSON.parse(document.getElementById("queryTagsInput").value || "{}");

      const result = await callApi("/query/tags", {
        method: "POST",
        body: JSON.stringify({ tags })
      });

      showResult("queryTagsResult", result);
    } catch (error) {
      showResult("queryTagsResult", { error: error.message });
    }
  });
}

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
    } catch (error) {
      showResult("querySpeciesResult", { error: error.message });
    }
  });
}

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

export function initMediaApiForm() {
  initQueryTags();
  initQuerySpecies();
  initQueryThumbnail();
  initBulkTags();
  initDeleteFiles();
}