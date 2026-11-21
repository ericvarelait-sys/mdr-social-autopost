/**
 * Disparador puntual en la nube (Google Apps Script - Gratis 24/7).
 * Reemplaza al reloj interno de GitHub Actions que sufre demoras/saltos.
 *
 * Configuracion (1 sola vez):
 * 1. Pegar este codigo en https://script.google.com/ (Nuevo proyecto).
 * 2. Reemplazar PEGAR_TU_GITHUB_TOKEN_AQUI con un Fine-Grained Token de GitHub
 *    con permiso "Actions: Read and write" sobre el repo mdr-social-autopost.
 * 3. Guardar, ejecutar verificarYPublicar una vez para autorizar permisos,
 *    y agregar un Activador (relojito izquierda) -> Segun el tiempo -> Cada 10 o 15 minutos.
 */

const GITHUB_OWNER = "ericvarelait-sys";
const GITHUB_REPO = "mdr-social-autopost";
const WORKFLOW_FILE = "autopost.yml";
const GITHUB_TOKEN = "PEGAR_TU_GITHUB_TOKEN_AQUI";

function verificarYPublicar() {
  const cb = Date.now();
  const schedUrl = `https://raw.githubusercontent.com/${GITHUB_OWNER}/${GITHUB_REPO}/main/schedule.json?cb=${cb}`;
  const stateUrl = `https://raw.githubusercontent.com/${GITHUB_OWNER}/${GITHUB_REPO}/main/state.json?cb=${cb}`;

  const sched = JSON.parse(UrlFetchApp.fetch(schedUrl, { muteHttpExceptions: false }).getContentText());
  const state = JSON.parse(UrlFetchApp.fetch(stateUrl, { muteHttpExceptions: false }).getContentText());
  const published = state.published || {};

  const nowMs = Date.now();
  const maxAgeMs = 36 * 60 * 60 * 1000; // 36 horas
  const props = PropertiesService.getScriptProperties();

  const due = (sched.items || []).filter((item) => {
    const rec = published[item.id] || {};
    if (rec.ig_id && rec.fb_id) return false;
    const schedMs = new Date(item.scheduled_at).getTime();
    const diff = nowMs - schedMs;
    return diff >= 0 && diff <= maxAgeMs;
  });

  if (due.length === 0) {
    Logger.log("Nada pendiente por publicar ahora.");
    return;
  }

  // Evita re-disparar el mismo ID si ya se disparo en los ultimos 8 minutos
  const lastKey = due.map((d) => d.id).join(",");
  const lastDispatchedKey = props.getProperty("LAST_KEY") || "";
  const lastDispatchedAt = Number(props.getProperty("LAST_AT") || "0");
  if (lastKey === lastDispatchedKey && (nowMs - lastDispatchedAt) < 8 * 60 * 1000) {
    Logger.log("Ya disparado hace menos de 8 minutos para: " + lastKey);
    return;
  }

  const dispatchUrl = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches`;
  const resp = UrlFetchApp.fetch(dispatchUrl, {
    method: "post",
    contentType: "application/json",
    headers: {
      Authorization: "Bearer " + GITHUB_TOKEN,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    payload: JSON.stringify({ ref: "main" }),
    muteHttpExceptions: true,
  });

  const code = resp.getResponseCode();
  if (code >= 200 && code < 300) {
    props.setProperty("LAST_KEY", lastKey);
    props.setProperty("LAST_AT", String(nowMs));
    Logger.log("Workflow disparado correctamente para: " + lastKey);
  } else {
    throw new Error("Error disparando GitHub Actions (" + code + "): " + resp.getContentText());
  }
}
