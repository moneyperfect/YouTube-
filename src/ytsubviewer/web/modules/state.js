/**
 * State management module for YTSubViewer
 */

export const appState = {
  currentWorkDir: "",
  currentTaskId: "",
  pollingHandle: null,
  pollTick: 0,
  stylePresets: [],
  performanceModes: [],
  providers: [],
  currentEditor: null,
  sessionToken: "",
  language: localStorage.getItem("ytsubviewer-lang") || "zh",
};

export function setCurrentWorkDir(dir) {
  appState.currentWorkDir = dir;
}

export function setCurrentTaskId(id) {
  appState.currentTaskId = id;
}

export function setSessionToken(token) {
  appState.sessionToken = token;
}

export function setLanguage(lang) {
  appState.language = lang;
  localStorage.setItem("ytsubviewer-lang", lang);
}

export function setStylePresets(presets) {
  appState.stylePresets = presets;
}

export function setPerformanceModes(modes) {
  appState.performanceModes = modes;
}

export function setProviders(providers) {
  appState.providers = providers;
}
