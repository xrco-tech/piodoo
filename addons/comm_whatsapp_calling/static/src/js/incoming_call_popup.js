/** @odoo-module **/

/**
 * Incoming WhatsApp call popup + WebRTC pipeline.
 *
 * Registered as an OWL service so bus_service can be resolved via the
 * standard dependency injection. The old approach of reaching for
 * `odoo.env.services.bus_service` off a global object doesn't work in
 * Odoo 18 — services are only available inside components / services.
 *
 * Flow:
 *   1. Meta webhook stores SDP offer on whatsapp.call.log.
 *   2. Server pushes { call_log_id, sdp_offer, partner_name, ... } over
 *      the whatsapp_incoming_call bus channel.
 *   3. This service shows a popup with Accept/Decline.
 *   4. On Accept: getUserMedia → RTCPeerConnection → setRemoteDescription
 *      (offer) → createAnswer → setLocalDescription → wait for ICE →
 *      POST answer to /whatsapp/call/answer/<id>.
 *   5. Server forwards answer to Meta.
 *   6. Meta establishes DTLS-SRTP; remote audio arrives via ontrack and
 *      plays through a hidden <audio autoplay>.
 */

import { registry } from "@web/core/registry";

const POPUP_ID = "comm_whatsapp_calling_incoming_popup";
const HUD_ID = "comm_whatsapp_calling_call_hud";
const SCRIPT_PANEL_ID = "comm_whatsapp_calling_script_panel";
const AUDIO_ID = "comm_whatsapp_calling_remote_audio";
const LOG_TAG = "[wa-call]";

const ICE_SERVERS = [
    { urls: "stun:stun.l.google.com:19302" },
    { urls: "stun:stun1.l.google.com:19302" },
];

// ── Theme ────────────────────────────────────────────────────────────
// Persisted per-browser (not per-user record) since this is a purely
// visual preference for floating widgets that live outside any view.
const THEME_STORAGE_KEY = "comm_whatsapp_calling_theme";
const THEMES = {
    dark: {
        card: "#111827", cardAlt: "#1f2937", text: "#fff", textMuted: "#9ca3af",
        border: "#1f2937", accent: "#25D366", primary: "#4a6cf7", danger: "#dc2626",
        inputBg: "#1f2937", inputBorder: "#374151", callBg: "rgba(37,211,102,0.15)",
        shadow: "0 10px 30px rgba(0,0,0,0.35)", shadowSm: "0 6px 18px rgba(0,0,0,0.25)",
    },
    light: {
        card: "#ffffff", cardAlt: "#f3f4f6", text: "#111827", textMuted: "#6b7280",
        border: "#e5e7eb", accent: "#128C7E", primary: "#4a6cf7", danger: "#dc2626",
        inputBg: "#f9fafb", inputBorder: "#d1d5db", callBg: "#d9ead3",
        shadow: "0 10px 30px rgba(0,0,0,0.15)", shadowSm: "0 6px 18px rgba(0,0,0,0.12)",
    },
};
function getStoredTheme() {
    try { return localStorage.getItem(THEME_STORAGE_KEY) === "dark" ? "dark" : "light"; }
    catch (e) { return "light"; }
}
function setStoredTheme(t) {
    try { localStorage.setItem(THEME_STORAGE_KEY, t); } catch (e) {}
}

function log(...args) {
    try { console.log(LOG_TAG, ...args); } catch (e) {}
}
function warn(...args) {
    try { console.warn(LOG_TAG, ...args); } catch (e) {}
}

function escapeHtml(s) {
    return String(s ?? "")
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function formatDuration(ms) {
    const totalSec = Math.max(0, Math.floor(ms / 1000));
    const m = Math.floor(totalSec / 60);
    const s = totalSec % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
}

function callRpc(url, params = {}) {
    const body = JSON.stringify({
        jsonrpc: "2.0",
        method: "call",
        params,
        id: Math.floor(Math.random() * 1e9),
    });
    return fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body,
    })
        .then((r) => r.json())
        .then((data) => {
            if (data.error) {
                throw new Error(
                    (data.error.data && data.error.data.message) ||
                    data.error.message || "RPC error"
                );
            }
            return data.result;
        });
}

function waitForIceGathering(pc, timeoutMs) {
    if (pc.iceGatheringState === "complete") return Promise.resolve();
    return new Promise((resolve) => {
        let done = false;
        function check() {
            if (done) return;
            if (pc.iceGatheringState === "complete") {
                done = true;
                pc.removeEventListener("icegatheringstatechange", check);
                resolve();
            }
        }
        pc.addEventListener("icegatheringstatechange", check);
        setTimeout(() => {
            if (!done) {
                done = true;
                pc.removeEventListener("icegatheringstatechange", check);
                resolve();
            }
        }, timeoutMs || 4000);
    });
}

function ensureRemoteAudioEl() {
    let el = document.getElementById(AUDIO_ID);
    if (el) return el;
    el = document.createElement("audio");
    el.id = AUDIO_ID;
    el.autoplay = true;
    el.setAttribute("playsinline", "");
    el.style.position = "fixed";
    el.style.left = "-9999px";
    document.body.appendChild(el);
    return el;
}

// ── Service ──────────────────────────────────────────────────────────

const waCallService = {
    dependencies: ["bus_service", "notification", "orm", "action"],
    start(env, { bus_service, notification, orm, action }) {
        log("service starting");

        // One active call at a time. Key = call_log_id.
        let activeCall = null;
        // { sessionId, chatbotName, bubbles, terminated } while a suggested
        // voice script is being followed for the current accepted call.
        let scriptSession = null;
        // Ticks the HUD's "In call for: mm:ss" label once a second.
        let hudTimerId = null;
        let theme = getStoredTheme();
        function colors() { return THEMES[theme]; }
        function themeToggleHtml() {
            const c = colors();
            return `<button data-action="theme-toggle" title="Switch to ${theme === "dark" ? "light" : "dark"} theme"
                        style="background:none;border:none;color:${c.textMuted};font-size:13px;cursor:pointer;padding:2px 4px;line-height:1;">
                        <i class="fa ${theme === "dark" ? "fa-sun-o" : "fa-moon-o"}"></i>
                    </button>`;
        }
        function wireThemeToggle(root, rerender) {
            const btn = root.querySelector('[data-action="theme-toggle"]');
            if (btn) {
                btn.addEventListener("click", () => {
                    theme = theme === "dark" ? "light" : "dark";
                    setStoredTheme(theme);
                    rerender();
                });
            }
        }
        // Small circular icon button used in every widget's "Shortcuts" row.
        function iconBtn(action, icon, title, extra = "") {
            const c = colors();
            return `<button data-action="${action}" title="${escapeHtml(title)}"
                         style="width:40px;height:40px;border-radius:50%;background:${c.cardAlt};color:${c.text};
                                border:none;font-size:15px;cursor:pointer;${extra}">
                        <i class="fa ${icon}"></i>
                    </button>`;
        }
        function shortcutsRowHtml(rows) {
            const c = colors();
            return `
                <div style="padding:12px 16px 4px;">
                    <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:${c.textMuted};margin-bottom:8px;">Shortcuts</div>
                    <div style="display:flex;gap:10px;">${rows.filter(Boolean).join("")}</div>
                </div>
            `;
        }

        function notify(message, type) {
            try {
                notification.add(message, { type: type || "info" });
            } catch (e) {
                log(message);
            }
        }

        function hidePopup() {
            const el = document.getElementById(POPUP_ID);
            if (el) el.remove();
        }

        function showPopup(payload) {
            hidePopup();
            const c = colors();
            const wrap = document.createElement("div");
            wrap.id = POPUP_ID;
            wrap.dataset.callLogId = payload.call_log_id;
            Object.assign(wrap.style, {
                position: "fixed", top: "20px", right: "20px",
                width: "280px", background: c.card, color: c.text,
                borderRadius: "10px", boxShadow: c.shadow,
                zIndex: "10000", overflow: "hidden",
                fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            });
            const scriptHint = payload.suggested_chatbot_id
                ? `<div style="font-size:11px;color:${c.accent};margin-top:10px;">
                       <i class="fa fa-list-alt me-1"></i>${escapeHtml(payload.suggested_chatbot_name || "")}
                   </div>`
                : "";
            const shortcuts = shortcutsRowHtml([
                payload.partner_id ? iconBtn("view-inbox", "fa-inbox", "View in Inbox") : "",
                iconBtn("change-script", "fa-list-alt", "Choose voice script"),
                payload.partner_id ? iconBtn("add-campaign", "fa-bullhorn", "Add to campaign") : "",
            ]);
            wrap.innerHTML = `
                <div style="background:#714B67;color:#fff;padding:8px 10px 8px 14px;display:flex;justify-content:space-between;align-items:center;">
                    <div style="font-size:13px;font-weight:600;">
                        <i class="fa fa-whatsapp me-1"></i>WhatsApp Call
                    </div>
                    <div style="display:flex;align-items:center;gap:2px;">
                        <button data-action="theme-toggle" title="Switch to ${theme === "dark" ? "light" : "dark"} theme"
                                style="background:none;border:none;color:rgba(255,255,255,0.85);font-size:12px;cursor:pointer;padding:4px;line-height:1;">
                            <i class="fa ${theme === "dark" ? "fa-sun-o" : "fa-moon-o"}"></i>
                        </button>
                        <button data-action="close" title="Decline"
                                style="background:none;border:none;color:rgba(255,255,255,0.85);font-size:16px;cursor:pointer;padding:4px 6px;line-height:1;">×</button>
                    </div>
                </div>
                <div style="padding:18px 16px 6px;text-align:center;">
                    <div style="font-size:12px;color:${c.textMuted};">Incoming call from...</div>
                    <div style="width:64px;height:64px;border-radius:50%;background:${c.cardAlt};display:flex;align-items:center;justify-content:center;margin:12px auto;">
                        <i class="fa fa-user" style="font-size:26px;color:${c.textMuted};"></i>
                    </div>
                    <div style="font-size:16px;font-weight:700;">${escapeHtml(payload.partner_name || "Unknown")}</div>
                    <div style="font-size:12px;color:${c.textMuted};margin-top:2px;">${escapeHtml(payload.from_number || "")}</div>
                    ${scriptHint}
                </div>
                ${shortcuts}
                <div style="display:flex;justify-content:center;gap:36px;padding:18px 16px 22px;">
                    <button data-action="decline" title="Decline"
                            style="width:52px;height:52px;border-radius:50%;background:${c.danger};color:#fff;border:none;font-size:18px;cursor:pointer;box-shadow:${c.shadowSm};">
                        <i class="fa fa-phone" style="transform:rotate(135deg);display:inline-block;"></i>
                    </button>
                    <button data-action="accept" title="Accept"
                            style="width:52px;height:52px;border-radius:50%;background:${c.accent};color:#fff;border:none;font-size:18px;cursor:pointer;box-shadow:${c.shadowSm};">
                        <i class="fa fa-phone"></i>
                    </button>
                </div>
            `;
            wrap.querySelector("[data-action=decline]").addEventListener("click", () => declineCall(payload.call_log_id));
            wrap.querySelector("[data-action=close]").addEventListener("click", () => declineCall(payload.call_log_id));
            wrap.querySelector("[data-action=accept]").addEventListener("click", () => acceptCall(payload));
            const inboxBtn = wrap.querySelector("[data-action=view-inbox]");
            if (inboxBtn) {
                inboxBtn.addEventListener("click", () => openContactInboxFor(payload.partner_id));
            }
            const changeScriptBtn = wrap.querySelector("[data-action=change-script]");
            if (changeScriptBtn) {
                changeScriptBtn.addEventListener("click", () => pickScriptForPopup(payload));
            }
            const addCampaignBtn = wrap.querySelector("[data-action=add-campaign]");
            if (addCampaignBtn) {
                addCampaignBtn.addEventListener("click", () => showCampaignPicker(payload.partner_id));
            }
            wireThemeToggle(wrap, () => showPopup(payload));
            document.body.appendChild(wrap);
        }

        function stopHudTimer() {
            if (hudTimerId) {
                clearInterval(hudTimerId);
                hudTimerId = null;
            }
        }

        function startHudTimer() {
            stopHudTimer();
            hudTimerId = setInterval(() => {
                const el = document.querySelector(`#${HUD_ID} [data-role=duration]`);
                if (!el || !activeCall || !activeCall.startTime) return;
                el.textContent = `In call for: ${formatDuration(Date.now() - activeCall.startTime)}`;
            }, 1000);
        }

        function toggleMute() {
            if (!activeCall || !activeCall.localStream) return;
            activeCall.muted = !activeCall.muted;
            activeCall.localStream.getAudioTracks().forEach((t) => { t.enabled = !activeCall.muted; });
        }

        // ── Recording (client-side — WhatsApp calls are end-to-end
        // encrypted between the browser and Meta, so there's nothing
        // server-side to record; the browser mixes both live audio
        // tracks itself and uploads the result once the call ends). ──
        function startRecording(call) {
            if (!call || !call.localStream || !call.remoteStream) {
                notify("Recording needs both sides of the call connected first.", "warning");
                return false;
            }
            try {
                const AudioCtx = window.AudioContext || window.webkitAudioContext;
                const audioCtx = new AudioCtx();
                const dest = audioCtx.createMediaStreamDestination();
                audioCtx.createMediaStreamSource(call.localStream).connect(dest);
                audioCtx.createMediaStreamSource(call.remoteStream).connect(dest);

                const chunks = [];
                const recorder = new MediaRecorder(dest.stream);
                recorder.ondataavailable = (ev) => {
                    if (ev.data && ev.data.size) chunks.push(ev.data);
                };
                recorder.start();

                call.audioContext = audioCtx;
                call.mediaRecorder = recorder;
                call.recordedChunks = chunks;
                call.recording = true;
                notify("Recording this call.", "info");
                return true;
            } catch (err) {
                warn("startRecording failed:", err);
                notify("Could not start recording: " + (err?.message || err), "danger");
                return false;
            }
        }

        async function stopRecordingAndUpload(call) {
            if (!call || !call.mediaRecorder) return;
            const recorder = call.mediaRecorder;
            const chunks = call.recordedChunks || [];
            const audioCtx = call.audioContext;
            call.mediaRecorder = null;
            call.recording = false;

            await new Promise((resolve) => {
                recorder.addEventListener("stop", resolve, { once: true });
                try { recorder.stop(); } catch (e) { resolve(); }
            });
            try { audioCtx && audioCtx.close(); } catch (e) {}

            if (!chunks.length || !call.id) return;
            const blob = new Blob(chunks, { type: "audio/webm" });
            const form = new FormData();
            form.append("recording", blob, "call_recording.webm");
            try {
                await fetch(`/whatsapp/call/upload_recording/${call.id}`, {
                    method: "POST", credentials: "same-origin", body: form,
                });
                log("recording uploaded for call", call.id);
            } catch (err) {
                warn("recording upload failed:", err);
                notify("Could not save the recording.", "warning");
            }
        }

        async function toggleRecording() {
            if (!activeCall) return;
            if (activeCall.recording) {
                await stopRecordingAndUpload(activeCall);
            } else {
                startRecording(activeCall);
            }
        }

        function showHud(payload) {
            const existing = document.getElementById(HUD_ID);
            if (existing) existing.remove();
            const c = colors();
            const connected = !!(activeCall && activeCall.startTime);
            const muted = !!(activeCall && activeCall.muted);
            const recording = !!(activeCall && activeCall.recording);
            const hud = document.createElement("div");
            hud.id = HUD_ID;
            Object.assign(hud.style, {
                position: "fixed", top: "20px", right: "20px",
                width: "280px", background: c.card, color: c.text,
                borderRadius: "10px", boxShadow: c.shadow,
                zIndex: "10000", overflow: "hidden",
                fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            });
            const shortcuts = shortcutsRowHtml([
                payload.partner_id ? iconBtn("view-inbox", "fa-inbox", "View in Inbox") : "",
                iconBtn("script", "fa-list-alt", scriptSession ? "Change voice script" : "Start voice script"),
                payload.partner_id ? iconBtn("add-campaign", "fa-bullhorn", "Add to campaign") : "",
                iconBtn("theme-toggle", theme === "dark" ? "fa-sun-o" : "fa-moon-o",
                         `Switch to ${theme === "dark" ? "light" : "dark"} theme`),
            ]);
            hud.innerHTML = `
                <div style="background:#714B67;color:#fff;padding:8px 10px 8px 14px;display:flex;justify-content:space-between;align-items:center;">
                    <div style="font-size:13px;font-weight:600;">
                        <i class="fa fa-whatsapp me-1"></i>WhatsApp Call
                    </div>
                    <button data-action="hangup" title="Hang up"
                            style="background:none;border:none;color:rgba(255,255,255,0.85);font-size:16px;cursor:pointer;padding:4px 6px;line-height:1;">×</button>
                </div>
                <div style="background:${c.callBg};padding:16px;text-align:center;">
                    <div style="width:64px;height:64px;border-radius:50%;background:${c.cardAlt};display:flex;align-items:center;justify-content:center;margin:0 auto 10px;overflow:hidden;">
                        <i class="fa fa-user" style="font-size:26px;color:${c.textMuted};"></i>
                    </div>
                    <div style="font-size:16px;font-weight:700;color:${c.text};">${escapeHtml(payload.partner_name || "In call")}</div>
                    <div data-role="duration" style="font-size:12px;color:${c.accent};font-weight:600;margin-top:2px;">
                        ${connected ? `In call for: ${formatDuration(Date.now() - activeCall.startTime)}` : "Calling…"}
                    </div>
                    ${payload.from_number ? `<div style="font-size:12px;color:${c.textMuted};margin-top:2px;">${escapeHtml(payload.from_number)}</div>` : ""}
                </div>
                ${shortcuts}
                <div style="padding:14px 16px 6px;border-top:1px solid ${c.border};margin-top:8px;">
                    <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:${c.textMuted};margin-bottom:8px;">Call</div>
                    <div style="display:flex;gap:10px;">
                        ${iconBtn("transfer", "fa-random", "Transfer to team")}
                        ${iconBtn("mute", muted ? "fa-microphone-slash" : "fa-microphone", muted ? "Unmute" : "Mute",
                                  muted ? `background:${c.danger};color:#fff;` : "")}
                        ${connected ? iconBtn("record", "fa-circle", recording ? "Stop recording" : "Record this call",
                                  recording ? `background:${c.danger};color:#fff;` : "") : ""}
                    </div>
                </div>
                <div style="display:flex;justify-content:center;padding:16px;">
                    <button data-action="hangup" title="Hang up"
                            style="width:52px;height:52px;border-radius:50%;background:${c.danger};color:#fff;border:none;font-size:18px;cursor:pointer;box-shadow:${c.shadowSm};">
                        <i class="fa fa-phone" style="transform:rotate(135deg);display:inline-block;"></i>
                    </button>
                </div>
            `;
            hud.querySelectorAll("[data-action=hangup]").forEach((btn) =>
                btn.addEventListener("click", () => hangupCall(payload.call_log_id)));
            hud.querySelector("[data-action=transfer]")
                .addEventListener("click", () => openTransferPicker(payload.call_log_id));
            hud.querySelector("[data-action=script]")
                .addEventListener("click", () => openScriptPicker());
            const inboxBtn = hud.querySelector("[data-action=view-inbox]");
            if (inboxBtn) {
                inboxBtn.addEventListener("click", () => openContactInboxFor(payload.partner_id));
            }
            const addCampaignBtn = hud.querySelector("[data-action=add-campaign]");
            if (addCampaignBtn) {
                addCampaignBtn.addEventListener("click", () => showCampaignPicker(payload.partner_id));
            }
            const muteBtn = hud.querySelector("[data-action=mute]");
            if (muteBtn) {
                muteBtn.addEventListener("click", () => { toggleMute(); showHud(payload); });
            }
            const recordBtn = hud.querySelector("[data-action=record]");
            if (recordBtn) {
                recordBtn.addEventListener("click", async () => { await toggleRecording(); showHud(payload); });
            }
            wireThemeToggle(hud, () => showHud(payload));
            document.body.appendChild(hud);
            if (connected) startHudTimer();
        }

        // ── Transfer request popup (target agent side) ─────────────
        const TRANSFER_POPUP_ID = "wa_transfer_request_popup";

        function showTransferRequestPopup(payload) {
            if (activeCall) {
                // Don't interrupt an active call — this popup can queue
                // as an alternative or just be skipped.
                notify(`Transfer request from ${payload.transferred_from_name} ignored (in call)`,
                       "info");
                return;
            }
            const existing = document.getElementById(TRANSFER_POPUP_ID);
            if (existing) existing.remove();

            const c = colors();
            const wrap = document.createElement("div");
            wrap.id = TRANSFER_POPUP_ID;
            wrap.dataset.sourceCallLogId = payload.source_call_log_id;
            Object.assign(wrap.style, {
                position: "fixed", top: "20px", right: "20px",
                width: "280px", background: c.card, color: c.text,
                borderRadius: "10px", boxShadow: c.shadow,
                zIndex: "10000", overflow: "hidden",
                fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            });
            const remove = () => wrap.remove();
            wrap.innerHTML = `
                <div style="background:#714B67;color:#fff;padding:8px 10px 8px 14px;display:flex;justify-content:space-between;align-items:center;">
                    <div style="font-size:13px;font-weight:600;">
                        <i class="fa fa-random me-1"></i>Call Transfer
                    </div>
                    <div style="display:flex;align-items:center;gap:2px;">
                        <button data-action="theme-toggle" title="Switch to ${theme === "dark" ? "light" : "dark"} theme"
                                style="background:none;border:none;color:rgba(255,255,255,0.85);font-size:12px;cursor:pointer;padding:4px;line-height:1;">
                            <i class="fa ${theme === "dark" ? "fa-sun-o" : "fa-moon-o"}"></i>
                        </button>
                        <button data-action="close" title="Decline"
                                style="background:none;border:none;color:rgba(255,255,255,0.85);font-size:16px;cursor:pointer;padding:4px 6px;line-height:1;">×</button>
                    </div>
                </div>
                <div style="padding:18px 16px 6px;text-align:center;">
                    <div style="font-size:12px;color:${c.textMuted};">
                        Transferred by ${escapeHtml(payload.transferred_from_name || "Someone")}
                    </div>
                    <div style="width:64px;height:64px;border-radius:50%;background:${c.cardAlt};display:flex;align-items:center;justify-content:center;margin:12px auto;">
                        <i class="fa fa-user" style="font-size:26px;color:${c.textMuted};"></i>
                    </div>
                    <div style="font-size:16px;font-weight:700;">${escapeHtml(payload.partner_name || "Caller")}</div>
                    <div style="font-size:12px;color:${c.textMuted};margin-top:2px;">${escapeHtml(payload.from_number || "")}</div>
                </div>
                <div style="display:flex;justify-content:center;gap:36px;padding:18px 16px 22px;">
                    <button data-action="decline" title="Decline"
                            style="width:52px;height:52px;border-radius:50%;background:${c.danger};color:#fff;border:none;font-size:18px;cursor:pointer;box-shadow:${c.shadowSm};">
                        <i class="fa fa-phone" style="transform:rotate(135deg);display:inline-block;"></i>
                    </button>
                    <button data-action="accept" title="Call back"
                            style="width:52px;height:52px;border-radius:50%;background:${c.accent};color:#fff;border:none;font-size:18px;cursor:pointer;box-shadow:${c.shadowSm};">
                        <i class="fa fa-phone"></i>
                    </button>
                </div>
            `;
            wrap.querySelector("[data-action=decline]").addEventListener("click", remove);
            wrap.querySelector("[data-action=close]").addEventListener("click", remove);
            wrap.querySelector("[data-action=accept]").addEventListener("click", async () => {
                remove();
                // Dial the customer back via the standard outbound path.
                // The new call log will get transferred_from_call_log_id
                // via a follow-up write from server side (not yet — cold
                // transfer means no continuity carried by Meta; this is
                // a fresh outbound call).
                await dialCall({
                    toNumber:    payload.from_number,
                    partnerId:   payload.partner_id || null,
                    partnerName: payload.partner_name || payload.from_number,
                    accountId:   payload.account_id || null,
                });
            });
            wireThemeToggle(wrap, () => showTransferRequestPopup(payload));
            document.body.appendChild(wrap);

            // If the transfer request stales (someone else accepted the
            // source call ended, etc.), auto-remove after 60s.
            setTimeout(() => {
                const el = document.getElementById(TRANSFER_POPUP_ID);
                if (el && +el.dataset.sourceCallLogId === payload.source_call_log_id) {
                    el.remove();
                }
            }, 60000);
        }

        // ── Transfer picker ────────────────────────────────────────
        async function openTransferPicker(callLogId) {
            let teams = [];
            try {
                const result = await callRpc("/whatsapp/call/teams", {});
                teams = result?.teams || [];
            } catch (err) {
                notify("Could not load teams: " + (err?.message || err),
                       "danger");
                return;
            }
            if (!teams.length) {
                notify("No call teams configured.", "warning");
                return;
            }
            // Remove any existing picker.
            const existing = document.getElementById("wa_transfer_picker");
            if (existing) existing.remove();

            const c = colors();
            const modal = document.createElement("div");
            modal.id = "wa_transfer_picker";
            Object.assign(modal.style, {
                position: "fixed", top: "20px", right: "20px",
                width: "280px", background: c.card, color: c.text,
                borderRadius: "10px", boxShadow: c.shadow,
                zIndex: "10001", overflow: "hidden",
                fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            });
            const rows = teams.map(t =>
                `<button data-team="${t.id}"
                         ${t.available_count === 0 ? "disabled" : ""}
                         style="display:flex;align-items:center;gap:10px;width:100%;text-align:left;
                                padding:10px 16px;background:transparent;
                                border:none;border-top:1px solid ${c.border};
                                color:${c.text};cursor:${t.available_count ? "pointer" : "default"};
                                opacity:${t.available_count ? "1" : "0.5"};">
                    <span style="width:32px;height:32px;flex:none;border-radius:50%;background:${c.cardAlt};display:flex;align-items:center;justify-content:center;">
                        <i class="fa fa-users" style="font-size:13px;color:${c.textMuted};"></i>
                    </span>
                    <span>
                        <div style="font-weight:600;font-size:13px;">${escapeHtml(t.name)}</div>
                        <div style="font-size:11px;color:${c.textMuted};">
                            ${t.available_count} of ${t.member_count} available
                        </div>
                    </span>
                </button>`
            ).join("");
            modal.innerHTML = `
                <div style="background:#714B67;color:#fff;padding:8px 10px 8px 14px;display:flex;justify-content:space-between;align-items:center;">
                    <div style="font-size:13px;font-weight:600;">
                        <i class="fa fa-random me-1"></i>Transfer to Team
                    </div>
                    <div style="display:flex;align-items:center;gap:2px;">
                        <button data-action="theme-toggle" title="Switch to ${theme === "dark" ? "light" : "dark"} theme"
                                style="background:none;border:none;color:rgba(255,255,255,0.85);font-size:12px;cursor:pointer;padding:4px;line-height:1;">
                            <i class="fa ${theme === "dark" ? "fa-sun-o" : "fa-moon-o"}"></i>
                        </button>
                        <button data-action="close" title="Close"
                                style="background:none;border:none;color:rgba(255,255,255,0.85);font-size:16px;cursor:pointer;padding:4px 6px;line-height:1;">×</button>
                    </div>
                </div>
                ${rows}
            `;
            modal.querySelector("[data-action=close]")
                 .addEventListener("click", () => modal.remove());
            wireThemeToggle(modal, () => openTransferPicker(callLogId));
            modal.querySelectorAll("[data-team]").forEach(btn => {
                if (btn.disabled) return;
                btn.addEventListener("click", async () => {
                    const teamId = +btn.dataset.team;
                    modal.remove();
                    try {
                        const result = await callRpc(
                            `/whatsapp/call/transfer/${callLogId}`,
                            { team_id: teamId },
                        );
                        if (!result?.success) {
                            throw new Error(result?.error || "Transfer failed");
                        }
                        notify(`Transferring — ${result.targets_notified} agent(s) notified`,
                               "success");
                        teardownCall(true);
                    } catch (err) {
                        notify("Transfer failed: " + (err?.message || err),
                               "danger");
                    }
                });
            });
            document.body.appendChild(modal);
        }

        // ── Voice script picker (start or switch mid-call) ──────────
        // Generic themed list picker used for both the mid-call "change
        // script" flow and the pre-accept "choose script" flow on the
        // incoming popup — onSelect(chatbotId, chatbotName) fires on click.
        async function showChatbotPicker(title, onSelect) {
            let chatbots = [];
            try {
                chatbots = await orm.searchRead(
                    "whatsapp.chatbot",
                    [["channel", "=", "voice"], ["status", "=", "published"]],
                    ["name"],
                );
            } catch (err) {
                notify("Could not load voice scripts: " + (err?.message || err), "danger");
                return;
            }
            if (!chatbots.length) {
                notify("No published voice scripts available.", "warning");
                return;
            }
            const existing = document.getElementById("wa_script_picker");
            if (existing) existing.remove();

            const c = colors();
            const modal = document.createElement("div");
            modal.id = "wa_script_picker";
            Object.assign(modal.style, {
                position: "fixed", top: "20px", right: "20px",
                width: "280px", background: c.card, color: c.text,
                borderRadius: "10px", boxShadow: c.shadow,
                zIndex: "10001", overflow: "hidden",
                fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            });
            const rows = chatbots.map((cb) =>
                `<button data-chatbot="${cb.id}"
                         style="display:flex;align-items:center;gap:10px;width:100%;text-align:left;
                                padding:10px 16px;background:transparent;
                                border:none;border-top:1px solid ${c.border};
                                color:${c.text};cursor:pointer;">
                    <span style="width:32px;height:32px;flex:none;border-radius:50%;background:${c.cardAlt};display:flex;align-items:center;justify-content:center;">
                        <i class="fa fa-list-alt" style="font-size:13px;color:${c.textMuted};"></i>
                    </span>
                    <span style="font-weight:600;font-size:13px;">${escapeHtml(cb.name)}</span>
                </button>`
            ).join("");
            modal.innerHTML = `
                <div style="background:#714B67;color:#fff;padding:8px 10px 8px 14px;display:flex;justify-content:space-between;align-items:center;">
                    <div style="font-size:13px;font-weight:600;">
                        <i class="fa fa-list-alt me-1"></i>${escapeHtml(title)}
                    </div>
                    <div style="display:flex;align-items:center;gap:2px;">
                        <button data-action="theme-toggle" title="Switch to ${theme === "dark" ? "light" : "dark"} theme"
                                style="background:none;border:none;color:rgba(255,255,255,0.85);font-size:12px;cursor:pointer;padding:4px;line-height:1;">
                            <i class="fa ${theme === "dark" ? "fa-sun-o" : "fa-moon-o"}"></i>
                        </button>
                        <button data-action="close" title="Close"
                                style="background:none;border:none;color:rgba(255,255,255,0.85);font-size:16px;cursor:pointer;padding:4px 6px;line-height:1;">×</button>
                    </div>
                </div>
                ${rows}
            `;
            modal.querySelector("[data-action=close]")
                 .addEventListener("click", () => modal.remove());
            wireThemeToggle(modal, () => showChatbotPicker(title, onSelect));
            modal.querySelectorAll("[data-chatbot]").forEach((btn) => {
                btn.addEventListener("click", () => {
                    const chatbotId = +btn.dataset.chatbot;
                    const chatbot = chatbots.find((cb) => cb.id === chatbotId);
                    modal.remove();
                    onSelect(chatbotId, chatbot ? chatbot.name : "Voice script");
                });
            });
            document.body.appendChild(modal);
        }

        async function openScriptPicker() {
            if (!activeCall) return;
            await showChatbotPicker(
                scriptSession ? "Change Voice Script" : "Start Voice Script",
                (chatbotId, chatbotName) => switchVoiceScript(chatbotId, chatbotName)
            );
        }

        // Pre-accept: let the agent override which script will run once
        // they answer, before the call (and any voice session) exists yet.
        async function pickScriptForPopup(payload) {
            await showChatbotPicker("Choose Voice Script", (chatbotId, chatbotName) => {
                payload.suggested_chatbot_id = chatbotId;
                payload.suggested_chatbot_name = chatbotName;
                showPopup(payload);
            });
        }

        // ── Add caller to a campaign (popup + HUD "Shortcuts") ──────
        async function showCampaignPicker(partnerId) {
            if (!partnerId) {
                notify("No linked contact for this call.", "warning");
                return;
            }
            let contacts = [];
            try {
                contacts = await orm.searchRead(
                    "contact.centre.contact", [["partner_id", "=", partnerId]],
                    ["id", "campaign_ids"], { limit: 1 },
                );
            } catch (err) {
                notify("Could not load the contact: " + (err?.message || err), "danger");
                return;
            }
            if (!contacts.length) {
                notify("This caller doesn't have a contact-centre record yet.", "warning");
                return;
            }
            const contact = contacts[0];
            let campaigns = [];
            try {
                campaigns = await orm.searchRead("contact.centre.campaign", [], ["name"]);
            } catch (err) {
                notify("Could not load campaigns: " + (err?.message || err), "danger");
                return;
            }
            if (!campaigns.length) {
                notify("No campaigns configured.", "warning");
                return;
            }
            const existing = document.getElementById("wa_campaign_picker");
            if (existing) existing.remove();

            const c = colors();
            const modal = document.createElement("div");
            modal.id = "wa_campaign_picker";
            Object.assign(modal.style, {
                position: "fixed", top: "20px", right: "20px",
                width: "280px", background: c.card, color: c.text,
                borderRadius: "10px", boxShadow: c.shadow,
                zIndex: "10001", overflow: "hidden",
                fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            });
            const already = new Set(contact.campaign_ids || []);
            const rows = campaigns.map((camp) => {
                const isIn = already.has(camp.id);
                return `<button data-campaign="${camp.id}" ${isIn ? "disabled" : ""}
                         style="display:flex;align-items:center;gap:10px;width:100%;text-align:left;
                                padding:10px 16px;background:transparent;
                                border:none;border-top:1px solid ${c.border};
                                color:${c.text};cursor:${isIn ? "default" : "pointer"};
                                opacity:${isIn ? "0.5" : "1"};">
                    <span style="width:32px;height:32px;flex:none;border-radius:50%;background:${c.cardAlt};display:flex;align-items:center;justify-content:center;">
                        <i class="fa fa-bullhorn" style="font-size:13px;color:${c.textMuted};"></i>
                    </span>
                    <span style="font-weight:600;font-size:13px;">
                        ${escapeHtml(camp.name)}${isIn ? " (added)" : ""}
                    </span>
                </button>`;
            }).join("");
            modal.innerHTML = `
                <div style="background:#714B67;color:#fff;padding:8px 10px 8px 14px;display:flex;justify-content:space-between;align-items:center;">
                    <div style="font-size:13px;font-weight:600;">
                        <i class="fa fa-bullhorn me-1"></i>Add to Campaign
                    </div>
                    <div style="display:flex;align-items:center;gap:2px;">
                        <button data-action="theme-toggle" title="Switch to ${theme === "dark" ? "light" : "dark"} theme"
                                style="background:none;border:none;color:rgba(255,255,255,0.85);font-size:12px;cursor:pointer;padding:4px;line-height:1;">
                            <i class="fa ${theme === "dark" ? "fa-sun-o" : "fa-moon-o"}"></i>
                        </button>
                        <button data-action="close" title="Close"
                                style="background:none;border:none;color:rgba(255,255,255,0.85);font-size:16px;cursor:pointer;padding:4px 6px;line-height:1;">×</button>
                    </div>
                </div>
                ${rows}
            `;
            modal.querySelector("[data-action=close]")
                 .addEventListener("click", () => modal.remove());
            wireThemeToggle(modal, () => showCampaignPicker(partnerId));
            modal.querySelectorAll("[data-campaign]").forEach((btn) => {
                if (btn.disabled) return;
                btn.addEventListener("click", async () => {
                    const campaignId = +btn.dataset.campaign;
                    modal.remove();
                    try {
                        await orm.write("contact.centre.contact", [contact.id], {
                            campaign_ids: [[4, campaignId]],
                        });
                        notify("Added to campaign.", "success");
                    } catch (err) {
                        notify("Could not add to campaign: " + (err?.message || err), "danger");
                    }
                });
            });
            document.body.appendChild(modal);
        }

        // ── Phone-number lookups (dial pad "Add to campaign" / "History") ──
        function normalizeDigits(s) {
            return String(s || "").replace(/[^0-9]/g, "");
        }

        async function resolveContactForNumber(rawNumber) {
            const digits = normalizeDigits(rawNumber);
            if (!digits) return null;
            // Match on the last 9 digits so formatting differences
            // (missing "+", country code, spaces) don't break the lookup.
            const suffix = digits.slice(-9);
            try {
                const contacts = await orm.searchRead(
                    "contact.centre.contact",
                    [["phone_number", "ilike", suffix]],
                    ["id", "partner_id"],
                    { limit: 1 },
                );
                return contacts[0] || null;
            } catch (e) {
                return null;
            }
        }

        // Resolves the "other party" of a call log row and places a call
        // to them immediately — used by both History and Contacts rows.
        async function callFromLog(l) {
            const toNumber = l.call_direction === "incoming" ? l.from_number : l.to_number;
            if (!toNumber) {
                notify("This call has no reachable number.", "warning");
                return;
            }
            await dialCall({
                toNumber,
                partnerId:   l.partner_id ? l.partner_id[0] : null,
                partnerName: l.contact_display || toNumber,
            });
        }

        async function fetchCallHistory(term) {
            const domain = [];
            const t = (term || "").trim();
            if (t) {
                const digits = normalizeDigits(t);
                const numberTerm = digits.length >= 3 ? digits.slice(-9) : t;
                domain.push("|", "|",
                    ["from_number", "ilike", numberTerm],
                    ["to_number", "ilike", numberTerm],
                    ["partner_id.name", "ilike", t]);
            }
            return orm.searchRead(
                "whatsapp.call.log", domain,
                ["call_direction", "call_status", "call_timestamp", "duration_display",
                 "is_missed", "from_number", "to_number", "partner_id", "contact_display",
                 "has_recording", "recording_ids"],
                { limit: 50, order: "call_timestamp desc" },
            );
        }

        function callHistoryRowsHtml(c, logs, emptyLabel) {
            if (!logs.length) {
                return `<div style="padding:20px 16px;color:${c.textMuted};font-size:13px;text-align:center;">${escapeHtml(emptyLabel)}</div>`;
            }
            return logs.map((l, i) => {
                const dirIcon = l.call_direction === "incoming" ? "fa-arrow-down" : "fa-arrow-up";
                const dirColor = l.is_missed ? c.danger : c.textMuted;
                const label = l.call_direction === "incoming"
                    ? (l.is_missed ? "Missed call" : "Incoming call")
                    : "Outgoing call";
                const who = l.contact_display
                    || (l.call_direction === "incoming" ? l.from_number : l.to_number)
                    || "Unknown";
                const when = l.call_timestamp ? String(l.call_timestamp).slice(0, 16) : "";
                const recordingId = l.has_recording && l.recording_ids && l.recording_ids[0];
                return `<div data-row="${i}"
                         style="display:flex;align-items:center;gap:10px;width:100%;text-align:left;
                                padding:10px 16px;background:transparent;
                                border-top:1px solid ${c.border};color:${c.text};cursor:pointer;">
                    <span style="width:32px;height:32px;flex:none;border-radius:50%;background:${c.cardAlt};display:flex;align-items:center;justify-content:center;">
                        <i class="fa ${dirIcon}" style="font-size:12px;color:${dirColor};"></i>
                    </span>
                    <span style="flex:1;min-width:0;">
                        <div style="font-weight:600;font-size:13px;color:${c.text};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(who)}</div>
                        <div style="font-size:11px;color:${dirColor};">${label} · ${escapeHtml(when)}</div>
                    </span>
                    <span style="font-size:11px;color:${c.textMuted};flex:none;">${escapeHtml(l.duration_display || "")}</span>
                    ${recordingId ? `<button data-play="${recordingId}" title="Play recording"
                            style="background:none;border:none;color:${c.accent};font-size:14px;cursor:pointer;padding:2px 4px;flex:none;">
                            <i class="fa fa-headphones"></i>
                        </button>` : ""}
                </div>`;
            }).join("");
        }

        async function showCallHistory() {
            const existing = document.getElementById("wa_call_history");
            if (existing) existing.remove();

            const c = colors();
            const modal = document.createElement("div");
            modal.id = "wa_call_history";
            Object.assign(modal.style, {
                position: "fixed", top: "20px", right: "20px",
                width: "300px", maxHeight: "70vh", display: "flex", flexDirection: "column",
                background: c.card, color: c.text,
                borderRadius: "10px", boxShadow: c.shadow,
                zIndex: "10001", overflow: "hidden",
                fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            });
            modal.innerHTML = `
                <div style="background:#714B67;color:#fff;padding:8px 10px 8px 14px;display:flex;justify-content:space-between;align-items:center;flex:none;">
                    <div style="font-size:13px;font-weight:600;">
                        <i class="fa fa-history me-1"></i>Call History
                    </div>
                    <div style="display:flex;align-items:center;gap:2px;">
                        <button data-action="theme-toggle" title="Switch to ${theme === "dark" ? "light" : "dark"} theme"
                                style="background:none;border:none;color:rgba(255,255,255,0.85);font-size:12px;cursor:pointer;padding:4px;line-height:1;">
                            <i class="fa ${theme === "dark" ? "fa-sun-o" : "fa-moon-o"}"></i>
                        </button>
                        <button data-action="close" title="Close"
                                style="background:none;border:none;color:rgba(255,255,255,0.85);font-size:16px;cursor:pointer;padding:4px 6px;line-height:1;">×</button>
                    </div>
                </div>
                <div style="padding:10px 14px;flex:none;">
                    <input data-role="search" type="text" placeholder="Search name or number…"
                           style="width:100%;box-sizing:border-box;background:${c.inputBg};border:1px solid ${c.inputBorder};border-radius:6px;color:${c.text};padding:7px 10px;font-size:13px;"/>
                </div>
                <div data-role="rows" style="overflow-y:auto;flex:1;">
                    <div style="padding:20px 16px;color:${c.textMuted};font-size:13px;text-align:center;">Loading…</div>
                </div>
            `;
            modal.querySelector("[data-action=close]")
                 .addEventListener("click", () => modal.remove());
            wireThemeToggle(modal, () => showCallHistory());
            document.body.appendChild(modal);

            const rowsEl = modal.querySelector("[data-role=rows]");
            const searchInput = modal.querySelector("[data-role=search]");
            let currentLogs = [];
            let debounceId = null;

            async function refresh(term) {
                let logs;
                try {
                    logs = await fetchCallHistory(term);
                } catch (err) {
                    rowsEl.innerHTML = `<div style="padding:20px 16px;color:${c.danger};font-size:13px;text-align:center;">Could not load call history.</div>`;
                    return;
                }
                if (!document.body.contains(modal)) return; // closed while awaiting
                currentLogs = logs;
                rowsEl.innerHTML = callHistoryRowsHtml(c, logs, term ? "No matching calls." : "No call history yet.");
                rowsEl.querySelectorAll("[data-row]").forEach((row) => {
                    row.addEventListener("click", async () => {
                        const log = currentLogs[+row.dataset.row];
                        modal.remove();
                        if (log) await callFromLog(log);
                    });
                });
                rowsEl.querySelectorAll("[data-play]").forEach((btn) => {
                    btn.addEventListener("click", (ev) => {
                        ev.stopPropagation();
                        // Dedicated streaming route, not /web/content — plays
                        // inline for anyone who can read the call; download
                        // stays gated to Call Recording Managers server-side.
                        window.open(`/whatsapp/call/recording/${btn.dataset.play}`, "_blank");
                    });
                });
            }

            searchInput.addEventListener("input", () => {
                clearTimeout(debounceId);
                debounceId = setTimeout(() => refresh(searchInput.value), 300);
            });
            refresh("");
        }

        // ── Contacts (dial pad "Contacts" shortcut) ──────────────────
        async function showContactsPicker() {
            const existing = document.getElementById("wa_contacts_picker");
            if (existing) existing.remove();

            const c = colors();
            const modal = document.createElement("div");
            modal.id = "wa_contacts_picker";
            Object.assign(modal.style, {
                position: "fixed", top: "20px", right: "20px",
                width: "300px", maxHeight: "70vh", display: "flex", flexDirection: "column",
                background: c.card, color: c.text,
                borderRadius: "10px", boxShadow: c.shadow,
                zIndex: "10001", overflow: "hidden",
                fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            });
            modal.innerHTML = `
                <div style="background:#714B67;color:#fff;padding:8px 10px 8px 14px;display:flex;justify-content:space-between;align-items:center;flex:none;">
                    <div style="font-size:13px;font-weight:600;">
                        <i class="fa fa-address-book me-1"></i>Contacts
                    </div>
                    <div style="display:flex;align-items:center;gap:2px;">
                        <button data-action="theme-toggle" title="Switch to ${theme === "dark" ? "light" : "dark"} theme"
                                style="background:none;border:none;color:rgba(255,255,255,0.85);font-size:12px;cursor:pointer;padding:4px;line-height:1;">
                            <i class="fa ${theme === "dark" ? "fa-sun-o" : "fa-moon-o"}"></i>
                        </button>
                        <button data-action="close" title="Close"
                                style="background:none;border:none;color:rgba(255,255,255,0.85);font-size:16px;cursor:pointer;padding:4px 6px;line-height:1;">×</button>
                    </div>
                </div>
                <div style="padding:10px 14px;flex:none;">
                    <input data-role="search" type="text" placeholder="Search contacts…"
                           style="width:100%;box-sizing:border-box;background:${c.inputBg};border:1px solid ${c.inputBorder};border-radius:6px;color:${c.text};padding:7px 10px;font-size:13px;"/>
                </div>
                <div data-role="rows" style="overflow-y:auto;flex:1;">
                    <div style="padding:20px 16px;color:${c.textMuted};font-size:13px;text-align:center;">Loading…</div>
                </div>
            `;
            modal.querySelector("[data-action=close]")
                 .addEventListener("click", () => modal.remove());
            wireThemeToggle(modal, () => showContactsPicker());
            document.body.appendChild(modal);

            const rowsEl = modal.querySelector("[data-role=rows]");
            const searchInput = modal.querySelector("[data-role=search]");
            let currentContacts = [];
            let debounceId = null;

            async function refresh(term) {
                const t = (term || "").trim();
                const domain = t
                    ? ["|", ["name", "ilike", t], ["phone_number", "ilike", t]]
                    : [];
                let contacts;
                try {
                    contacts = await orm.searchRead(
                        "contact.centre.contact", domain,
                        ["name", "phone_number", "partner_id"],
                        { limit: 50, order: "name" },
                    );
                } catch (err) {
                    rowsEl.innerHTML = `<div style="padding:20px 16px;color:${c.danger};font-size:13px;text-align:center;">Could not load contacts.</div>`;
                    return;
                }
                if (!document.body.contains(modal)) return;
                currentContacts = contacts.filter((ct) => ct.phone_number);
                rowsEl.innerHTML = currentContacts.length ? currentContacts.map((ct, i) => `
                    <button data-row="${i}"
                            style="display:flex;align-items:center;gap:10px;width:100%;text-align:left;
                                   padding:10px 16px;background:transparent;border:none;
                                   border-top:1px solid ${c.border};color:${c.text};cursor:pointer;">
                        <span style="width:32px;height:32px;flex:none;border-radius:50%;background:${c.cardAlt};display:flex;align-items:center;justify-content:center;">
                            <i class="fa fa-user" style="font-size:13px;color:${c.textMuted};"></i>
                        </span>
                        <span style="flex:1;min-width:0;">
                            <div style="font-weight:600;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(ct.name || ct.phone_number)}</div>
                            <div style="font-size:11px;color:${c.textMuted};">${escapeHtml(ct.phone_number)}</div>
                        </span>
                        <i class="fa fa-phone" style="font-size:13px;color:${c.accent};flex:none;"></i>
                    </button>
                `).join("") : `<div style="padding:20px 16px;color:${c.textMuted};font-size:13px;text-align:center;">${t ? "No matching contacts." : "No contacts yet."}</div>`;
                rowsEl.querySelectorAll("[data-row]").forEach((btn) => {
                    btn.addEventListener("click", async () => {
                        const ct = currentContacts[+btn.dataset.row];
                        modal.remove();
                        if (!ct) return;
                        await dialCall({
                            toNumber:    ct.phone_number,
                            partnerId:   ct.partner_id ? ct.partner_id[0] : null,
                            partnerName: ct.name || ct.phone_number,
                        });
                    });
                });
            }

            searchInput.addEventListener("input", () => {
                clearTimeout(debounceId);
                debounceId = setTimeout(() => refresh(searchInput.value), 300);
            });
            refresh("");
        }

        async function switchVoiceScript(chatbotId, chatbotName) {
            if (!activeCall) return;
            if (scriptSession?.sessionId) {
                try {
                    await callRpc("/voice/end", { session_id: scriptSession.sessionId });
                } catch (e) {
                    // Best-effort — proceeding to start the new one regardless.
                }
            }
            scriptSession = null;
            hideScriptPanel();
            await startVoiceScript({
                suggested_chatbot_id: chatbotId,
                suggested_chatbot_name: chatbotName,
                partner_name: activeCall.partnerName,
                from_number: activeCall.fromNumber,
            });
        }

        // ── Jump to the caller's conversation in the Inbox ──────────
        async function openContactInboxFor(partnerId) {
            if (!partnerId) {
                notify("No linked contact for this call.", "warning");
                return;
            }
            let contacts = [];
            try {
                contacts = await orm.searchRead(
                    "contact.centre.contact", [["partner_id", "=", partnerId]], ["id"], { limit: 1 },
                );
            } catch (err) {
                notify("Could not open the Inbox: " + (err?.message || err), "danger");
                return;
            }
            if (!contacts.length) {
                notify("This caller doesn't have a contact-centre record yet.", "warning");
                return;
            }
            action.doAction({
                type: "ir.actions.client",
                tag: "contact_centre_inbox",
                target: "new",
                context: { dialog_size: "extra-large" },
                params: { contact_id: contacts[0].id },
            });
        }

        function hideHud() {
            stopHudTimer();
            const hud = document.getElementById(HUD_ID);
            if (hud) hud.remove();
        }

        // ── Suggested voice script (accepted inbound calls only) ────
        // Mirrors contact_centre_inbox's VoiceScriptPanel (same /voice/*
        // endpoints) as plain DOM instead of an OWL component - this
        // service floats outside any view's component tree (a call can
        // ring in from anywhere in the app), and comm_whatsapp_calling
        // doesn't depend on contact_centre_inbox, so it can't import that
        // component directly.
        function hideScriptPanel() {
            const el = document.getElementById(SCRIPT_PANEL_ID);
            if (el) el.remove();
        }

        function renderScriptPanel() {
            if (!scriptSession) return;
            hideScriptPanel();
            const c = colors();
            const panel = document.createElement("div");
            panel.id = SCRIPT_PANEL_ID;
            Object.assign(panel.style, {
                // Sits to the left of the HUD (280px wide + 20px gaps)
                // rather than stacked under it, so it doesn't collide with
                // the HUD's own height changing as call state changes.
                position: "fixed", top: "20px", right: "320px",
                width: "340px", maxHeight: "80vh", display: "flex", flexDirection: "column",
                background: c.card, color: c.text, borderRadius: "10px",
                boxShadow: c.shadow, zIndex: "10000", overflow: "hidden",
                fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            });
            const bubblesHtml = scriptSession.bubbles.map((b) => `
                <div style="background:${c.cardAlt};border-radius:8px;padding:8px 10px;margin-bottom:8px;font-size:13px;white-space:pre-wrap;">
                    ${escapeHtml(b.body || "")}
                </div>
            `).join("");
            panel.innerHTML = `
                <div style="background:#714B67;color:#fff;padding:8px 10px 8px 14px;display:flex;justify-content:space-between;align-items:center;">
                    <div style="font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:200px;">
                        <i class="fa fa-list-alt me-1"></i>${escapeHtml(scriptSession.chatbotName)}
                    </div>
                    <div style="display:flex;align-items:center;gap:2px;">
                        <button data-action="change-script" title="Change script"
                                style="background:none;border:none;color:rgba(255,255,255,0.85);font-size:13px;cursor:pointer;padding:4px;line-height:1;">
                            <i class="fa fa-exchange"></i>
                        </button>
                        <button data-action="theme-toggle" title="Switch to ${theme === "dark" ? "light" : "dark"} theme"
                                style="background:none;border:none;color:rgba(255,255,255,0.85);font-size:12px;cursor:pointer;padding:4px;line-height:1;">
                            <i class="fa ${theme === "dark" ? "fa-sun-o" : "fa-moon-o"}"></i>
                        </button>
                        <button data-action="close" title="End script"
                                style="background:none;border:none;color:rgba(255,255,255,0.85);font-size:16px;cursor:pointer;padding:4px 6px;line-height:1;">×</button>
                    </div>
                </div>
                <div style="padding:10px 14px;overflow-y:auto;flex:1;">
                    ${bubblesHtml}
                    ${scriptSession.loading ? `<div style="font-size:12px;color:${c.textMuted};">Loading next step…</div>` : ""}
                </div>
                ${scriptSession.terminated
                    ? `<div style="padding:10px 14px;color:${c.accent};font-size:12px;">Script complete.</div>`
                    : `<div style="display:flex;gap:8px;padding:10px 14px;border-top:1px solid ${c.border};">
                           <input data-role="input" type="text" placeholder="Customer's answer…"
                                  style="flex:1;background:${c.inputBg};border:1px solid ${c.inputBorder};border-radius:6px;color:${c.text};padding:6px 8px;font-size:13px;"/>
                           <button data-action="send" style="background:${c.accent};color:#fff;border:none;border-radius:6px;padding:0 12px;font-weight:700;cursor:pointer;">Send</button>
                       </div>`
                }
            `;
            panel.querySelector("[data-action=close]").addEventListener("click", () => endVoiceScript());
            panel.querySelector("[data-action=change-script]").addEventListener("click", () => openScriptPicker());
            wireThemeToggle(panel, () => renderScriptPanel());
            const sendBtn = panel.querySelector("[data-action=send]");
            const input = panel.querySelector("[data-role=input]");
            if (sendBtn && input) {
                const submit = () => {
                    const text = input.value.trim();
                    if (text) sendScriptTurn(text);
                };
                sendBtn.addEventListener("click", submit);
                input.addEventListener("keydown", (ev) => {
                    if (ev.key === "Enter") submit();
                });
            }
            document.body.appendChild(panel);
        }

        async function startVoiceScript(payload) {
            scriptSession = {
                sessionId: null, chatbotName: payload.suggested_chatbot_name || "Voice script",
                bubbles: [], terminated: false, loading: true,
            };
            renderScriptPanel();
            try {
                const result = await callRpc("/voice/start", {
                    chatbot_id: payload.suggested_chatbot_id,
                    contact_details: { name: payload.partner_name, mobile: payload.from_number },
                });
                if (!scriptSession) return; // call ended while starting
                if (result?.error || !result?.session_id) {
                    throw new Error(result?.error || "No session id returned");
                }
                scriptSession.sessionId = result.session_id;
                await sendScriptTurn(null);
            } catch (err) {
                warn("voice script start failed:", err);
                notify("Could not start the suggested script: " + (err?.message || err), "warning");
                scriptSession = null;
                hideScriptPanel();
            }
        }

        async function sendScriptTurn(userInput) {
            if (!scriptSession || !scriptSession.sessionId) return;
            scriptSession.loading = true;
            renderScriptPanel();
            try {
                const data = await callRpc("/voice/turn", {
                    session_id: scriptSession.sessionId,
                    user_input: userInput,
                    initial_variables: {},
                });
                if (!scriptSession) return; // call ended mid-turn
                scriptSession.bubbles = scriptSession.bubbles.concat(data.bubbles || []);
                scriptSession.terminated = !!data.terminate;
            } catch (err) {
                warn("voice script turn failed:", err);
                notify("Script error — the turn failed to advance.", "danger");
            } finally {
                if (scriptSession) {
                    scriptSession.loading = false;
                    renderScriptPanel();
                }
            }
        }

        async function endVoiceScript() {
            const session = scriptSession;
            scriptSession = null;
            hideScriptPanel();
            if (session?.sessionId) {
                try {
                    await callRpc("/voice/end", { session_id: session.sessionId });
                } catch (e) {
                    // Best-effort — the call itself still ends via hangupActive below.
                }
            }
            hangupActive();
        }

        async function acceptCall(payload) {
            if (!payload || !payload.call_log_id || !payload.sdp_offer) {
                notify("Cannot accept: missing SDP offer.", "danger");
                return;
            }
            if (activeCall) {
                notify("Another call is in progress.", "warning");
                return;
            }
            hidePopup();
            notify("Connecting…", "info");

            const call = {
                id: payload.call_log_id,
                pc: null, localStream: null, remoteStream: null,
                partnerName: payload.partner_name || payload.from_number,
                fromNumber: payload.from_number,
                partnerId: payload.partner_id || null,
                startTime: null, muted: false,
                recording: false, mediaRecorder: null, recordedChunks: [], audioContext: null,
            };
            activeCall = call;

            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
                call.localStream = stream;

                const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
                call.pc = pc;

                pc.onicecandidate = (ev) => {
                    if (!ev.candidate) log("ICE gathering complete");
                };
                pc.onconnectionstatechange = () => {
                    log("connection state:", pc.connectionState);
                    if (pc.connectionState === "failed" || pc.connectionState === "closed") {
                        teardownCall(false);
                    }
                };
                pc.oniceconnectionstatechange = () => log("ICE state:", pc.iceConnectionState);
                pc.ontrack = (ev) => {
                    log("ontrack:", ev.streams?.[0]);
                    const audio = ensureRemoteAudioEl();
                    if (ev.streams?.[0]) {
                        audio.srcObject = ev.streams[0];
                        call.remoteStream = ev.streams[0];
                    }
                };

                stream.getAudioTracks().forEach((t) => pc.addTrack(t, stream));

                await pc.setRemoteDescription({ type: "offer", sdp: payload.sdp_offer });
                const answer = await pc.createAnswer();
                await pc.setLocalDescription(answer);
                await waitForIceGathering(pc, 4000);

                const result = await callRpc(
                    `/whatsapp/call/answer/${call.id}`,
                    { sdp_answer: pc.localDescription.sdp },
                );
                if (!result?.success) {
                    throw new Error(result?.error || "Accept failed");
                }
                notify("Call connected.", "success");
                call.startTime = Date.now();
                showHud(payload);
                if (payload.suggested_chatbot_id) {
                    startVoiceScript(payload);
                }
            } catch (err) {
                warn("accept failed:", err);
                notify("Accept failed: " + (err?.message || err), "danger");
                teardownCall(false);
            }
        }

        function declineCall(callLogId) {
            hidePopup();
            callRpc(`/whatsapp/call/decline/${callLogId}`, {})
                .then(() => notify("Call declined.", "info"))
                .catch((err) => notify("Decline failed: " + (err?.message || err), "danger"));
        }

        function hangupCall(callLogId) {
            teardownCall(true);
            callRpc(`/whatsapp/call/decline/${callLogId}`, {}).catch(() => {});
        }

        function teardownCall(userInitiated) {
            if (!activeCall) return;
            if (activeCall.recording) {
                // Fire-and-forget: don't block teardown on the upload,
                // and the call object is captured by reference so this
                // still has its streams even after activeCall is nulled.
                stopRecordingAndUpload(activeCall);
            }
            try { activeCall.pc?.close(); } catch (e) {}
            try {
                activeCall.localStream?.getTracks().forEach((t) => t.stop());
            } catch (e) {}
            const audio = document.getElementById(AUDIO_ID);
            if (audio) audio.srcObject = null;
            activeCall = null;
            hideHud();
            // Call ended via some other path (HUD hangup, remote hung up,
            // connection failure) while a script was in progress - end that
            // session too rather than leaving it dangling server-side.
            // endVoiceScript() itself calls hangupActive() (which re-enters
            // here), so this must clear scriptSession first to avoid a loop.
            if (scriptSession) {
                const session = scriptSession;
                scriptSession = null;
                hideScriptPanel();
                if (session.sessionId) {
                    callRpc("/voice/end", { session_id: session.sessionId }).catch(() => {});
                }
            }
            if (!userInitiated) notify("Call ended.", "info");
        }

        // ── Call permission request (offered after a "no permission"
        // dial failure) ──────────────────────────────────────────────
        async function offerCallPermissionRequest(toNumber, accountId, partnerName) {
            const existing = document.getElementById("wa_call_permission_prompt");
            if (existing) existing.remove();
            const c = colors();
            const wrap = document.createElement("div");
            wrap.id = "wa_call_permission_prompt";
            Object.assign(wrap.style, {
                position: "fixed", top: "20px", right: "20px",
                width: "280px", background: c.card, color: c.text,
                borderRadius: "10px", boxShadow: c.shadow,
                zIndex: "10001", overflow: "hidden",
                fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            });
            wrap.innerHTML = `
                <div style="background:#714B67;color:#fff;padding:8px 10px 8px 14px;display:flex;justify-content:space-between;align-items:center;">
                    <div style="font-size:13px;font-weight:600;">
                        <i class="fa fa-shield me-1"></i>Call Permission Needed
                    </div>
                    <div style="display:flex;align-items:center;gap:2px;">
                        <button data-action="theme-toggle" title="Switch to ${theme === "dark" ? "light" : "dark"} theme"
                                style="background:none;border:none;color:rgba(255,255,255,0.85);font-size:12px;cursor:pointer;padding:4px;line-height:1;">
                            <i class="fa ${theme === "dark" ? "fa-sun-o" : "fa-moon-o"}"></i>
                        </button>
                        <button data-action="close" title="Dismiss"
                                style="background:none;border:none;color:rgba(255,255,255,0.85);font-size:16px;cursor:pointer;padding:4px 6px;line-height:1;">×</button>
                    </div>
                </div>
                <div style="padding:16px;">
                    <div style="font-size:13px;color:${c.text};line-height:1.4;">
                        ${escapeHtml(partnerName || toNumber)} hasn't granted this number permission to call them on WhatsApp yet.
                    </div>
                    <div style="font-size:12px;color:${c.textMuted};margin-top:8px;">
                        Send a call permission request so they can approve it, then try calling again.
                    </div>
                </div>
                <div style="display:flex;gap:8px;padding:0 16px 16px;">
                    <button data-action="dismiss" style="flex:1;background:${c.cardAlt};color:${c.text};border:none;border-radius:8px;padding:10px 0;font-weight:700;cursor:pointer;">Dismiss</button>
                    <button data-action="send" style="flex:1;background:${c.accent};color:#fff;border:none;border-radius:8px;padding:10px 0;font-weight:700;cursor:pointer;">Send Request</button>
                </div>
            `;
            wrap.querySelector("[data-action=close]").addEventListener("click", () => wrap.remove());
            wrap.querySelector("[data-action=dismiss]").addEventListener("click", () => wrap.remove());
            wrap.querySelector("[data-action=send]").addEventListener("click", async () => {
                wrap.remove();
                notify("Sending call permission request…", "info");
                try {
                    const result = await callRpc("/whatsapp/call/request_permission", {
                        to_number: toNumber, account_id: accountId || null,
                        partner_name: partnerName || null,
                    });
                    if (result?.success) {
                        notify("Call permission request sent. Ask them to accept it in WhatsApp, then try calling again.", "success");
                    } else if (result?.error === "template_missing") {
                        notify("Call permission not granted by user. Ensure that the call permission template is available and try again.", "danger");
                    } else {
                        notify("Failed to send permission request: " + (result?.error || "Unknown error"), "danger");
                    }
                } catch (err) {
                    notify("Failed to send permission request: " + (err?.message || err), "danger");
                }
            });
            wireThemeToggle(wrap, () => offerCallPermissionRequest(toNumber, accountId, partnerName));
            document.body.appendChild(wrap);
        }

        // ── Outbound dial ─────────────────────────────────────────────
        async function dialCall({ toNumber, accountId, partnerName, partnerId, chatbotId, chatbotName }) {
            if (!toNumber) {
                notify("Enter a phone number to dial.", "warning");
                return;
            }
            if (activeCall) {
                notify("Another call is in progress.", "warning");
                return;
            }
            notify(`Dialling ${toNumber}…`, "info");

            const call = {
                id: null, pc: null, localStream: null,
                remoteStream: null, direction: "outgoing",
                partnerName: partnerName || toNumber,
                fromNumber: toNumber,
                partnerId: partnerId || null,
                chatbotId: chatbotId || null,
                chatbotName: chatbotName || "",
                startTime: null, muted: false,
                recording: false, mediaRecorder: null, recordedChunks: [], audioContext: null,
            };
            activeCall = call;

            try {
                const stream = await navigator.mediaDevices.getUserMedia({
                    audio: true, video: false,
                });
                call.localStream = stream;

                const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
                call.pc = pc;

                pc.onicecandidate = (ev) => {
                    if (!ev.candidate) log("outbound ICE gathering complete");
                };
                pc.onconnectionstatechange = () => {
                    log("outbound connection state:", pc.connectionState);
                    if (pc.connectionState === "failed" || pc.connectionState === "closed") {
                        teardownCall(false);
                    }
                };
                pc.oniceconnectionstatechange = () =>
                    log("outbound ICE state:", pc.iceConnectionState);
                pc.ontrack = (ev) => {
                    log("outbound ontrack:", ev.streams?.[0]);
                    const audio = ensureRemoteAudioEl();
                    if (ev.streams?.[0]) {
                        audio.srcObject = ev.streams[0];
                        call.remoteStream = ev.streams[0];
                    }
                };

                stream.getAudioTracks().forEach((t) => pc.addTrack(t, stream));

                // Create and set offer, wait for ICE.
                const offer = await pc.createOffer();
                await pc.setLocalDescription(offer);
                await waitForIceGathering(pc, 4000);

                const result = await callRpc("/whatsapp/call/dial", {
                    to_number:  toNumber,
                    sdp_offer:  pc.localDescription.sdp,
                    account_id: accountId || null,
                    partner_id: partnerId || null,
                    chatbot_id: chatbotId || null,
                });
                if (!result?.success) {
                    throw new Error(result?.error || "Dial failed");
                }
                call.id = result.call_log_id;
                showHud({
                    call_log_id:  call.id,
                    partner_name: call.partnerName,
                    from_number:  call.fromNumber,
                    partner_id:   call.partnerId,
                });
                notify("Ringing…", "info");
                // Now wait for the whatsapp_outbound_answered bus event
                // to deliver the SDP answer.
            } catch (err) {
                warn("dial failed:", err);
                const message = err?.message || String(err);
                notify("Dial failed: " + message, "danger");
                teardownCall(false);
                if (/no approved call permission/i.test(message)) {
                    offerCallPermissionRequest(toNumber, accountId, partnerName);
                }
            }
        }

        async function handleOutboundAnswered(payload) {
            if (!activeCall || activeCall.direction !== "outgoing") {
                warn("outbound answered but no active outbound call");
                return;
            }
            if (activeCall.id && payload.call_log_id !== activeCall.id) {
                warn("outbound answered for a different call_log_id");
                return;
            }
            try {
                await activeCall.pc.setRemoteDescription({
                    type: "answer", sdp: payload.sdp_answer,
                });
                log("outbound remote description set — audio should establish");
                notify("Connected.", "success");
                activeCall.startTime = Date.now();
                showHud({
                    call_log_id:  activeCall.id,
                    partner_name: activeCall.partnerName || "In call",
                    from_number:  activeCall.fromNumber,
                    partner_id:   activeCall.partnerId,
                });
                if (activeCall.chatbotId) {
                    startVoiceScript({
                        suggested_chatbot_id:   activeCall.chatbotId,
                        suggested_chatbot_name: activeCall.chatbotName,
                        partner_name:           activeCall.partnerName,
                        from_number:            activeCall.fromNumber,
                    });
                }
            } catch (err) {
                warn("setRemoteDescription failed:", err);
                notify("Media negotiation failed.", "danger");
                teardownCall(false);
            }
        }

        function hangupActive() {
            if (!activeCall) return false;
            const id = activeCall.id;
            teardownCall(true);
            if (id) {
                callRpc(`/whatsapp/call/decline/${id}`, {}).catch(() => {});
            }
            return true;
        }

        function isActive() {
            return !!activeCall;
        }

        // ── Dial pad (opened from the systray phone icon) ───────────
        // Same VoIP-card look as the incoming popup/HUD, driven by the
        // same theme system, so it's light-by-default like the rest.
        const DIALPAD_ID = "comm_whatsapp_calling_dialpad";

        function hideDialPad() {
            const el = document.getElementById(DIALPAD_ID);
            if (el) el.remove();
        }

        async function openDialPad() {
            if (activeCall) {
                notify("Another call is in progress.", "warning");
                return;
            }
            hideDialPad();
            const c = colors();
            let accounts = [];
            let selectedAccountId = null;
            try {
                const result = await callRpc("/whatsapp/call/accounts", {});
                accounts = result?.accounts || [];
                selectedAccountId = result?.default_id || (accounts[0] && accounts[0].id) || null;
            } catch (e) {
                warn("account fetch failed:", e);
            }

            const wrap = document.createElement("div");
            wrap.id = DIALPAD_ID;
            Object.assign(wrap.style, {
                position: "fixed", top: "20px", right: "20px",
                width: "280px", background: c.card, color: c.text,
                borderRadius: "10px", boxShadow: c.shadow,
                zIndex: "10000", overflow: "hidden",
                fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            });
            const accountOptions = accounts.map((a) =>
                `<option value="${a.id}" ${a.id === selectedAccountId ? "selected" : ""}>
                    ${escapeHtml((a.phone_number || a.name) + (a.is_default ? " (default)" : ""))}
                 </option>`
            ).join("");
            // Chosen via the "Voice Script" shortcut below — kept outside
            // any re-render so picking a script doesn't clear the number
            // the agent already typed.
            let selectedChatbotId = null;
            let selectedChatbotName = "";
            const shortcuts = shortcutsRowHtml([
                iconBtn("script", "fa-list-alt", "Choose voice script"),
                iconBtn("add-campaign", "fa-bullhorn", "Add to campaign"),
                iconBtn("history", "fa-history", "Call history"),
                iconBtn("contacts", "fa-address-book", "Contacts"),
            ]);
            wrap.innerHTML = `
                <div style="background:#714B67;color:#fff;padding:8px 10px 8px 14px;display:flex;justify-content:space-between;align-items:center;">
                    <div style="font-size:13px;font-weight:600;">
                        <i class="fa fa-whatsapp me-1"></i>New Call
                    </div>
                    <div style="display:flex;align-items:center;gap:2px;">
                        <button data-action="theme-toggle" title="Switch to ${theme === "dark" ? "light" : "dark"} theme"
                                style="background:none;border:none;color:rgba(255,255,255,0.85);font-size:12px;cursor:pointer;padding:4px;line-height:1;">
                            <i class="fa ${theme === "dark" ? "fa-sun-o" : "fa-moon-o"}"></i>
                        </button>
                        <button data-action="close" title="Close"
                                style="background:none;border:none;color:rgba(255,255,255,0.85);font-size:16px;cursor:pointer;padding:4px 6px;line-height:1;">×</button>
                    </div>
                </div>
                <div style="padding:18px 16px 6px;text-align:center;">
                    <div style="width:64px;height:64px;border-radius:50%;background:${c.cardAlt};display:flex;align-items:center;justify-content:center;margin:0 auto 14px;">
                        <i class="fa fa-phone" style="font-size:24px;color:${c.textMuted};"></i>
                    </div>
                    ${accounts.length > 1 ? `
                    <select data-role="account" style="width:100%;box-sizing:border-box;background:${c.inputBg};border:1px solid ${c.inputBorder};border-radius:6px;color:${c.text};padding:7px 8px;font-size:12px;margin-bottom:10px;">
                        ${accountOptions}
                    </select>` : ""}
                    <input data-role="number" type="tel" placeholder="+27600000000"
                           style="width:100%;box-sizing:border-box;background:${c.inputBg};border:1px solid ${c.inputBorder};border-radius:6px;color:${c.text};padding:9px 10px;font-size:14px;text-align:center;"/>
                    <div data-role="script-hint" style="display:none;font-size:11px;color:${c.accent};margin-top:8px;">
                        <i class="fa fa-list-alt me-1"></i><span data-role="script-hint-text"></span>
                    </div>
                </div>
                ${shortcuts}
                <div style="display:flex;justify-content:center;padding:14px 16px 20px;">
                    <button data-action="dial" title="Call"
                            style="width:52px;height:52px;border-radius:50%;background:${c.accent};color:#fff;border:none;font-size:18px;cursor:pointer;box-shadow:${c.shadowSm};">
                        <i class="fa fa-phone"></i>
                    </button>
                </div>
            `;
            const numberInput = wrap.querySelector("[data-role=number]");
            const accountSelect = wrap.querySelector("[data-role=account]");
            const scriptHint = wrap.querySelector("[data-role=script-hint]");
            const scriptHintText = wrap.querySelector("[data-role=script-hint-text]");
            const dial = async () => {
                const to = (numberInput.value || "").trim();
                if (!to) {
                    notify("Enter a number to dial.", "warning");
                    return;
                }
                const accountId = accountSelect ? +accountSelect.value : selectedAccountId;
                hideDialPad();
                await dialCall({
                    toNumber: to, accountId: accountId || null,
                    chatbotId: selectedChatbotId || null, chatbotName: selectedChatbotName,
                });
            };
            wrap.querySelector("[data-action=dial]").addEventListener("click", dial);
            numberInput.addEventListener("keydown", (ev) => { if (ev.key === "Enter") dial(); });
            wrap.querySelector("[data-action=close]").addEventListener("click", () => hideDialPad());
            wrap.querySelector("[data-action=script]").addEventListener("click", () => {
                showChatbotPicker("Choose Voice Script", (chatbotId, chatbotName) => {
                    selectedChatbotId = chatbotId;
                    selectedChatbotName = chatbotName;
                    scriptHintText.textContent = chatbotName;
                    scriptHint.style.display = "block";
                });
            });
            wrap.querySelector("[data-action=add-campaign]").addEventListener("click", async () => {
                const to = (numberInput.value || "").trim();
                if (!to) {
                    notify("Enter a number first.", "warning");
                    return;
                }
                const contact = await resolveContactForNumber(to);
                if (!contact) {
                    notify("No matching contact found for this number.", "warning");
                    return;
                }
                showCampaignPicker(contact.partner_id ? contact.partner_id[0] : false);
            });
            wrap.querySelector("[data-action=history]").addEventListener("click", () => {
                showCallHistory();
            });
            wrap.querySelector("[data-action=contacts]").addEventListener("click", () => {
                showContactsPicker();
            });
            wireThemeToggle(wrap, () => openDialPad());
            document.body.appendChild(wrap);
            numberInput.focus();
        }

        // Public API for other components (systray, res.partner button,
        // Agent Workspace, etc.).
        env.services.comm_whatsapp_calling = { dialCall, hangupActive, isActive, openDialPad };

        // ── Bus wiring ────────────────────────────────────────────────
        try {
            log("bus_service keys:", Object.keys(bus_service));
            if (typeof bus_service.subscribe !== "function") {
                warn("bus_service.subscribe is not a function — API changed?");
                return { dialCall, hangupActive, isActive, openDialPad };
            }
            bus_service.subscribe("whatsapp_incoming_call", (payload) => {
                log("bus event received:", payload?.type, "id:", payload?.call_log_id);
                if (payload?.type === "whatsapp_incoming_call") {
                    showPopup(payload);
                }
            });
            bus_service.subscribe("whatsapp_outbound_answered", (payload) => {
                log("outbound answered:", payload?.call_log_id);
                handleOutboundAnswered(payload);
            });
            bus_service.subscribe("whatsapp_transfer_request", (payload) => {
                log("transfer request received:", payload?.source_call_log_id);
                showTransferRequestPopup(payload);
            });
            bus_service.subscribe("whatsapp_call_taken", (payload) => {
                // Fired when: (a) another agent accepted / declined /
                // hung up, or (b) the remote side ended the call
                // (verb === "remote_ended"). We do THREE things here:
                //  1. Kill our ringing popup if it's for this call.
                //  2. If our active call matches this id, tear it down —
                //     stops audio, closes the PC, removes the HUD.
                //  3. Skip step 1 (but NOT step 2) for the session that
                //     initiated the action so the accepting/hanging-up
                //     agent's own UI isn't clobbered before their flow
                //     completes.
                if (!payload || !payload.call_log_id) return;
                const myUid = env.services.user && env.services.user.userId;
                const isSelf = payload.taken_by_uid
                    && myUid && payload.taken_by_uid === myUid;

                // (1) popup dismissal — skip for the acting user.
                if (!isSelf) {
                    const el = document.getElementById(POPUP_ID);
                    if (el && +el.dataset.callLogId === payload.call_log_id) {
                        log("call taken elsewhere, hiding popup:", payload);
                        el.remove();
                    }
                }

                // (2) HUD + PC teardown when the remote hung up on us.
                // This runs for the active session too — if the caller
                // dropped, our audio needs to stop regardless of who
                // triggered the event.
                const isRemoteEnd = payload.verb === "remote_ended";
                if (isRemoteEnd
                        && activeCall
                        && activeCall.id === payload.call_log_id) {
                    log("remote party ended the call; tearing down");
                    teardownCall(false);
                }
            });
            if (typeof bus_service.start === "function") {
                bus_service.start();
            }
            log("bus subscribed and started");
        } catch (e) {
            warn("bus subscribe failed:", e && e.message ? e.message : e);
        }

        return { dialCall, hangupActive, isActive, openDialPad };
    },
};

registry.category("services").add("comm_whatsapp_calling", waCallService);
