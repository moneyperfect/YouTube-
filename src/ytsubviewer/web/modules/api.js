/**
 * API module for YTSubViewer
 * Handles all HTTP requests to the backend.
 */

export async function request(path, options = {}, sessionToken = "") {
  const headers = { "Content-Type": "application/json" };
  if (sessionToken) {
    headers["Authorization"] = `Bearer ${sessionToken}`;
  }
  const response = await fetch(path, {
    headers,
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    throw new Error(detail || `请求失败 (${response.status})`);
  }
  return data;
}

export async function bootstrap(token) {
  return request("/api/bootstrap", { method: "GET" }, token);
}

export async function saveSettings(payload, token) {
  return request("/api/settings", {
    method: "POST",
    body: JSON.stringify(payload),
  }, token);
}

export async function testProvider(payload, token) {
  return request("/api/settings/test", {
    method: "POST",
    body: JSON.stringify(payload),
  }, token);
}

export async function analyzeVideo(payload, token) {
  return request("/api/analyze", {
    method: "POST",
    body: JSON.stringify(payload),
  }, token);
}

export async function generateSubtitle(payload, token) {
  return request("/api/generate", {
    method: "POST",
    body: JSON.stringify(payload),
  }, token);
}

export async function batchGenerate(payload, token) {
  return request("/api/batch", {
    method: "POST",
    body: JSON.stringify(payload),
  }, token);
}

export async function getCurrentJob(token) {
  return request("/api/job/current", { method: "GET" }, token);
}

export async function getJobHistory(token) {
  return request("/api/job/history", { method: "GET" }, token);
}

export async function cancelJob(taskId, token) {
  return request(`/api/job/${encodeURIComponent(taskId)}/cancel`, {
    method: "POST",
  }, token);
}

export async function retryJob(taskId, token) {
  return request(`/api/job/${encodeURIComponent(taskId)}/retry`, {
    method: "POST",
  }, token);
}

export async function exportVideo(payload, token) {
  return request("/api/export", {
    method: "POST",
    body: JSON.stringify(payload),
  }, token);
}

export async function openPlayer(payload, token) {
  return request("/api/open-player", {
    method: "POST",
    body: JSON.stringify(payload),
  }, token);
}

export async function loadEditor(taskId, params, token) {
  const query = new URLSearchParams(params).toString();
  return request(`/api/job/${encodeURIComponent(taskId)}/editor?${query}`, {
    method: "GET",
  }, token);
}

export async function updateCue(taskId, payload, token) {
  return request(`/api/job/${encodeURIComponent(taskId)}/cue/update`, {
    method: "POST",
    body: JSON.stringify(payload),
  }, token);
}

export async function retranslateCue(taskId, payload, token) {
  return request(`/api/job/${encodeURIComponent(taskId)}/cue/retranslate`, {
    method: "POST",
    body: JSON.stringify(payload),
  }, token);
}

export async function lockCue(taskId, payload, token) {
  return request(`/api/job/${encodeURIComponent(taskId)}/cue/lock`, {
    method: "POST",
    body: JSON.stringify(payload),
  }, token);
}

export async function bulkReplace(taskId, payload, token) {
  return request(`/api/job/${encodeURIComponent(taskId)}/cue/bulk-replace`, {
    method: "POST",
    body: JSON.stringify(payload),
  }, token);
}

export async function youtubeLogin(token) {
  return request("/api/youtube-login", {
    method: "POST",
  }, token);
}

export async function saveCreatorProfile(payload, token) {
  return request("/api/creator-profile/save", {
    method: "POST",
    body: JSON.stringify(payload),
  }, token);
}

export async function activateLicense(payload, token) {
  return request("/api/license/activate", {
    method: "POST",
    body: JSON.stringify(payload),
  }, token);
}

export async function deactivateLicense(token) {
  return request("/api/license/deactivate", {
    method: "POST",
  }, token);
}

export async function verifyLicense(payload, token) {
  return request("/api/license/verify", {
    method: "POST",
    body: JSON.stringify(payload),
  }, token);
}
