/**
 * Utility functions for YTSubViewer
 */

export function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

export function formatDuration(seconds) {
  if (!seconds) return "-";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function firstUrlFromInput(textarea) {
  const urls = textarea.value
    .replaceAll("\r", "\n")
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
  return urls[0] || "";
}

export function collectTaskPayload(elements) {
  return {
    url: firstUrlFromInput(elements.urlInput),
    style_preset: elements.styleSelect.value,
    glossary_text: elements.glossaryInput.value.trim(),
    protected_terms_text: elements.protectedTermsInput.value.trim(),
    performance_mode: elements.performanceSelect.value,
    use_creator_defaults: elements.creatorDefaultsToggle.checked,
  };
}

export function collectBatchPayload(elements) {
  return {
    urls_text: elements.urlInput.value.trim(),
    style_preset: elements.styleSelect.value,
    glossary_text: elements.glossaryInput.value.trim(),
    protected_terms_text: elements.protectedTermsInput.value.trim(),
    performance_mode: elements.performanceSelect.value,
    use_creator_defaults: elements.creatorDefaultsToggle.checked,
  };
}
