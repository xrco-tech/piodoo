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
    dependencies: ["bus_service", "notification"],
    start(env, { bus_service, notification }) {
        log("service starting");

        // One active call at a time. Key = call_log_id.
        let activeCall = null;
        // { sessionId, chatbotName, bubbles, terminated } while a suggested
        // voice script is being followed for the current accepted call.
        let scriptSession = null;

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
            const wrap = document.createElement("div");
            wrap.id = POPUP_ID;
            wrap.dataset.callLogId = payload.call_log_id;
            Object.assign(wrap.style, {
                position: "fixed", top: "20px", right: "20px",
                width: "340px", background: "#111827", color: "#fff",
                borderRadius: "12px", boxShadow: "0 10px 30px rgba(0,0,0,0.35)",
                zIndex: "10000", overflow: "hidden",
                fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            });
            const scriptHint = payload.suggested_chatbot_id
                ? `<div style="font-size:12px;color:#25D366;margin-top:8px;">
                       <i class="fa fa-list-alt me-1"/>Suggested script: ${escapeHtml(payload.suggested_chatbot_name || "")}
                   </div>`
                : "";
            wrap.innerHTML = `
                <div style="padding:14px 16px;">
                    <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.7px;color:#25D366;font-weight:700;margin-bottom:6px;">
                        📞 Incoming WhatsApp call
                    </div>
                    <div style="font-size:15px;font-weight:600;">${escapeHtml(payload.partner_name || "Unknown")}</div>
                    <div style="font-size:12px;color:#9ca3af;margin-top:2px;">${escapeHtml(payload.from_number || "")}</div>
                    ${scriptHint}
                </div>
                <div style="display:flex;gap:8px;padding:0 16px 14px;">
                    <button data-action="decline" style="flex:1;background:#dc2626;color:#fff;border:none;border-radius:8px;padding:10px 0;font-weight:700;cursor:pointer;">Decline</button>
                    <button data-action="accept" style="flex:1;background:#25D366;color:#fff;border:none;border-radius:8px;padding:10px 0;font-weight:700;cursor:pointer;">Accept</button>
                </div>
            `;
            wrap.querySelector("[data-action=decline]").addEventListener("click", () => declineCall(payload.call_log_id));
            wrap.querySelector("[data-action=accept]").addEventListener("click", () => acceptCall(payload));
            document.body.appendChild(wrap);
        }

        function showHud(payload) {
            const existing = document.getElementById(HUD_ID);
            if (existing) existing.remove();
            const hud = document.createElement("div");
            hud.id = HUD_ID;
            Object.assign(hud.style, {
                position: "fixed", top: "20px", right: "20px",
                background: "#111827", color: "#fff",
                padding: "10px 14px", borderRadius: "999px",
                boxShadow: "0 6px 18px rgba(0,0,0,0.25)",
                display: "flex", alignItems: "center", gap: "10px",
                zIndex: "10000",
                fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
                fontSize: "13px", fontWeight: "600",
            });
            hud.innerHTML = `
                <span style="width:8px;height:8px;background:#25D366;border-radius:50%;animation:wa-pulse 1.4s infinite;"></span>
                <span>${escapeHtml(payload.partner_name || "In call")}</span>
                <button data-action="transfer" title="Transfer to team"
                        style="background:#4a6cf7;color:#fff;border:none;border-radius:999px;width:28px;height:28px;font-weight:700;cursor:pointer;">
                    <i class="fa fa-random"/>
                </button>
                <button data-action="hangup" style="background:#dc2626;color:#fff;border:none;border-radius:999px;width:28px;height:28px;font-weight:700;cursor:pointer;">✕</button>
                <style>@keyframes wa-pulse{0%{box-shadow:0 0 0 0 rgba(37,211,102,0.7);}70%{box-shadow:0 0 0 10px rgba(37,211,102,0);}100%{box-shadow:0 0 0 0 rgba(37,211,102,0);}}</style>
            `;
            hud.querySelector("[data-action=hangup]")
                .addEventListener("click", () => hangupCall(payload.call_log_id));
            hud.querySelector("[data-action=transfer]")
                .addEventListener("click", () => openTransferPicker(payload.call_log_id));
            document.body.appendChild(hud);
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

            const wrap = document.createElement("div");
            wrap.id = TRANSFER_POPUP_ID;
            wrap.dataset.sourceCallLogId = payload.source_call_log_id;
            Object.assign(wrap.style, {
                position: "fixed", top: "20px", right: "20px",
                width: "340px", background: "#111827", color: "#fff",
                borderRadius: "12px",
                boxShadow: "0 10px 30px rgba(0,0,0,0.35)",
                zIndex: "10000", overflow: "hidden",
                fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            });
            wrap.innerHTML = `
                <div style="padding:14px 16px;">
                    <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.7px;color:#4a6cf7;font-weight:700;margin-bottom:6px;">
                        <i class="fa fa-random me-1"/>Call transfer request
                    </div>
                    <div style="font-size:14px;color:#9ca3af;margin-bottom:4px;">
                        ${escapeHtml(payload.transferred_from_name || "Someone")}
                        is transferring a call
                    </div>
                    <div style="font-size:15px;font-weight:600;">${escapeHtml(payload.partner_name || "Caller")}</div>
                    <div style="font-size:12px;color:#9ca3af;margin-top:2px;">${escapeHtml(payload.from_number || "")}</div>
                </div>
                <div style="display:flex;gap:8px;padding:0 16px 14px;">
                    <button data-action="decline" style="flex:1;background:#374151;color:#fff;border:none;border-radius:8px;padding:10px 0;font-weight:700;cursor:pointer;">Decline</button>
                    <button data-action="accept" style="flex:1;background:#25D366;color:#fff;border:none;border-radius:8px;padding:10px 0;font-weight:700;cursor:pointer;">Call back</button>
                </div>
            `;
            wrap.querySelector("[data-action=decline]").addEventListener("click", () => wrap.remove());
            wrap.querySelector("[data-action=accept]").addEventListener("click", async () => {
                wrap.remove();
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

            const modal = document.createElement("div");
            modal.id = "wa_transfer_picker";
            Object.assign(modal.style, {
                position: "fixed", top: "60px", right: "20px",
                width: "320px", background: "#111827", color: "#fff",
                borderRadius: "12px",
                boxShadow: "0 10px 30px rgba(0,0,0,0.35)",
                zIndex: "10001", overflow: "hidden",
                fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            });
            const rows = teams.map(t =>
                `<button data-team="${t.id}"
                         ${t.available_count === 0 ? "disabled" : ""}
                         style="display:block;width:100%;text-align:left;
                                padding:10px 14px;background:transparent;
                                border:none;border-top:1px solid #1f2937;
                                color:#fff;cursor:${t.available_count ? "pointer" : "default"};
                                opacity:${t.available_count ? "1" : "0.5"};">
                    <div style="font-weight:600;">${escapeHtml(t.name)}</div>
                    <div style="font-size:11px;color:#9ca3af;">
                        ${t.available_count} of ${t.member_count} available
                    </div>
                </button>`
            ).join("");
            modal.innerHTML = `
                <div style="padding:12px 14px;font-size:12px;text-transform:uppercase;color:#9ca3af;letter-spacing:0.4px;display:flex;justify-content:space-between;align-items:center;">
                    <span>Transfer to team</span>
                    <button data-action="close" style="background:none;border:none;color:#9ca3af;font-size:18px;cursor:pointer;">×</button>
                </div>
                ${rows}
            `;
            modal.querySelector("[data-action=close]")
                 .addEventListener("click", () => modal.remove());
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

        function hideHud() {
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
            const panel = document.createElement("div");
            panel.id = SCRIPT_PANEL_ID;
            Object.assign(panel.style, {
                position: "fixed", top: "80px", right: "20px",
                width: "340px", maxHeight: "60vh", display: "flex", flexDirection: "column",
                background: "#111827", color: "#fff", borderRadius: "12px",
                boxShadow: "0 10px 30px rgba(0,0,0,0.35)", zIndex: "10000",
                fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            });
            const bubblesHtml = scriptSession.bubbles.map((b) => `
                <div style="background:#1f2937;border-radius:8px;padding:8px 10px;margin-bottom:8px;font-size:13px;white-space:pre-wrap;">
                    ${escapeHtml(b.body || "")}
                </div>
            `).join("");
            panel.innerHTML = `
                <div style="padding:10px 14px;border-bottom:1px solid #1f2937;display:flex;justify-content:space-between;align-items:center;">
                    <div style="font-size:12px;text-transform:uppercase;letter-spacing:0.5px;color:#25D366;font-weight:700;">
                        <i class="fa fa-list-alt me-1"/>${escapeHtml(scriptSession.chatbotName)}
                    </div>
                    <button data-action="close" style="background:none;border:none;color:#9ca3af;font-size:16px;cursor:pointer;">×</button>
                </div>
                <div style="padding:10px 14px;overflow-y:auto;flex:1;">
                    ${bubblesHtml}
                    ${scriptSession.loading ? '<div style="font-size:12px;color:#9ca3af;">Loading next step…</div>' : ""}
                </div>
                ${scriptSession.terminated
                    ? '<div style="padding:10px 14px;color:#25D366;font-size:12px;">Script complete.</div>'
                    : `<div style="display:flex;gap:8px;padding:10px 14px;border-top:1px solid #1f2937;">
                           <input data-role="input" type="text" placeholder="Customer's answer…"
                                  style="flex:1;background:#1f2937;border:1px solid #374151;border-radius:6px;color:#fff;padding:6px 8px;font-size:13px;"/>
                           <button data-action="send" style="background:#25D366;color:#fff;border:none;border-radius:6px;padding:0 12px;font-weight:700;cursor:pointer;">Send</button>
                       </div>`
                }
            `;
            panel.querySelector("[data-action=close]").addEventListener("click", () => endVoiceScript());
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

        // ── Outbound dial ─────────────────────────────────────────────
        async function dialCall({ toNumber, accountId, partnerName, partnerId, chatbotId }) {
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
                    partner_name: `Calling ${partnerName || toNumber}…`,
                });
                notify("Ringing…", "info");
                // Now wait for the whatsapp_outbound_answered bus event
                // to deliver the SDP answer.
            } catch (err) {
                warn("dial failed:", err);
                notify("Dial failed: " + (err?.message || err), "danger");
                teardownCall(false);
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
                showHud({
                    call_log_id:  activeCall.id,
                    partner_name: activeCall.partnerName || "In call",
                });
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

        // Public API for other components (systray, res.partner button,
        // Agent Workspace, etc.).
        env.services.comm_whatsapp_calling = { dialCall, hangupActive, isActive };

        // ── Bus wiring ────────────────────────────────────────────────
        try {
            log("bus_service keys:", Object.keys(bus_service));
            if (typeof bus_service.subscribe !== "function") {
                warn("bus_service.subscribe is not a function — API changed?");
                return { dialCall, hangupActive, isActive };
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

        return { dialCall, hangupActive, isActive };
    },
};

registry.category("services").add("comm_whatsapp_calling", waCallService);
