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
            wrap.innerHTML = `
                <div style="padding:14px 16px;">
                    <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.7px;color:#25D366;font-weight:700;margin-bottom:6px;">
                        📞 Incoming WhatsApp call
                    </div>
                    <div style="font-size:15px;font-weight:600;">${escapeHtml(payload.partner_name || "Unknown")}</div>
                    <div style="font-size:12px;color:#9ca3af;margin-top:2px;">${escapeHtml(payload.from_number || "")}</div>
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
                <button data-action="hangup" style="background:#dc2626;color:#fff;border:none;border-radius:999px;width:28px;height:28px;font-weight:700;cursor:pointer;">✕</button>
                <style>@keyframes wa-pulse{0%{box-shadow:0 0 0 0 rgba(37,211,102,0.7);}70%{box-shadow:0 0 0 10px rgba(37,211,102,0);}100%{box-shadow:0 0 0 0 rgba(37,211,102,0);}}</style>
            `;
            hud.querySelector("[data-action=hangup]").addEventListener("click", () => hangupCall(payload.call_log_id));
            document.body.appendChild(hud);
        }

        function hideHud() {
            const hud = document.getElementById(HUD_ID);
            if (hud) hud.remove();
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
