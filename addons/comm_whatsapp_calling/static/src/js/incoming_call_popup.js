/**
 * Incoming WhatsApp call popup + WebRTC pipeline.
 *
 * Listens on the Odoo bus for `whatsapp_incoming_call` events, shows a
 * popup with Accept/Decline, and (on Accept) drives a real
 * RTCPeerConnection so DTLS-SRTP actually establishes and audio flows.
 *
 * Flow when a call comes in:
 *   1. Meta webhook stores the SDP offer on whatsapp.call.log.
 *   2. Server pushes { call_log_id, sdp_offer, partner_name, ... }
 *      over the whatsapp_incoming_call bus channel.
 *   3. This module shows a popup.
 *   4. User clicks Accept →
 *        - getUserMedia({audio: true}) captures the microphone.
 *        - Create RTCPeerConnection with STUN.
 *        - setRemoteDescription(offer).
 *        - createAnswer() → setLocalDescription(answer).
 *        - Wait for ICE gathering to complete (short timeout).
 *        - POST answer SDP to /whatsapp/call/answer/<id>.
 *   5. Server forwards answer to Meta with action=accept.
 *   6. Meta establishes DTLS-SRTP; remote audio arrives via pc.ontrack.
 *   7. An <audio> element plays the remote stream.
 *
 * Hangup is exposed as a floating pill in the top-right corner while
 * a call is active.
 */

(function () {
    "use strict";

    var POPUP_ID = "comm_whatsapp_calling_incoming_popup";
    var HUD_ID   = "comm_whatsapp_calling_call_hud";
    var AUDIO_ID = "comm_whatsapp_calling_remote_audio";
    var LOG_TAG  = "[wa-call]";

    // STUN only for now — Meta's SDP typically carries its own TURN
    // candidates. If you need TURN for restrictive NATs, deploy coturn
    // and add its config to iceServers below.
    var ICE_SERVERS = [
        { urls: "stun:stun.l.google.com:19302" },
        { urls: "stun:stun1.l.google.com:19302" },
    ];

    // ── State ────────────────────────────────────────────────────────────
    // One active call at a time. Key = call_log_id.
    var activeCall = null;   // { id, pc, localStream, remoteStream, hangupSent }

    function log() {
        try { console.log.apply(console, [LOG_TAG].concat([].slice.call(arguments))); } catch (e) {}
    }
    function warn() {
        try { console.warn.apply(console, [LOG_TAG].concat([].slice.call(arguments))); } catch (e) {}
    }

    // ── Odoo bus + notification helpers ──────────────────────────────────
    function notify(message, type) {
        try {
            if (odoo && odoo.env && odoo.env.services && odoo.env.services.notification) {
                odoo.env.services.notification.add(message, { type: type || "info" });
                return;
            }
        } catch (e) {}
        log(message);
    }

    function callRpc(url, params) {
        params = params || {};
        var body = JSON.stringify({
            jsonrpc: "2.0",
            method: "call",
            params: params,
            id: Math.floor(Math.random() * 1e9),
        });
        var headers = { "Content-Type": "application/json" };
        return fetch(url, {
            method: "POST",
            credentials: "same-origin",
            headers: headers,
            body: body,
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.error) {
                    throw new Error((data.error.data && data.error.data.message) || data.error.message || "RPC error");
                }
                return data.result;
            });
    }

    // ── Popup UI ─────────────────────────────────────────────────────────
    function ensureRemoteAudioEl() {
        var el = document.getElementById(AUDIO_ID);
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

    function hidePopup() {
        var el = document.getElementById(POPUP_ID);
        if (el) el.remove();
    }

    function showPopup(payload) {
        hidePopup();
        var wrap = document.createElement("div");
        wrap.id = POPUP_ID;
        wrap.style.position = "fixed";
        wrap.style.top = "20px";
        wrap.style.right = "20px";
        wrap.style.width = "340px";
        wrap.style.background = "#111827";
        wrap.style.color = "#fff";
        wrap.style.borderRadius = "12px";
        wrap.style.boxShadow = "0 10px 30px rgba(0,0,0,0.35)";
        wrap.style.zIndex = "10000";
        wrap.style.overflow = "hidden";
        wrap.style.fontFamily = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";

        var body = document.createElement("div");
        body.style.padding = "14px 16px";
        body.innerHTML =
            '<div style="font-size:11px;text-transform:uppercase;letter-spacing:0.7px;color:#25D366;font-weight:700;margin-bottom:6px;">' +
            '📞 Incoming WhatsApp call</div>' +
            '<div style="font-size:15px;font-weight:600;">' + escapeHtml(payload.partner_name || "Unknown") + '</div>' +
            '<div style="font-size:12px;color:#9ca3af;margin-top:2px;">' + escapeHtml(payload.from_number || "") + '</div>';
        wrap.appendChild(body);

        var actions = document.createElement("div");
        actions.style.display = "flex";
        actions.style.gap = "8px";
        actions.style.padding = "0 16px 14px";
        actions.innerHTML =
            '<button data-action="decline" style="flex:1;background:#dc2626;color:#fff;border:none;border-radius:8px;padding:10px 0;font-weight:700;cursor:pointer;">Decline</button>' +
            '<button data-action="accept" style="flex:1;background:#25D366;color:#fff;border:none;border-radius:8px;padding:10px 0;font-weight:700;cursor:pointer;">Accept</button>';
        wrap.appendChild(actions);

        actions.querySelector("[data-action=decline]").addEventListener("click", function () {
            declineCall(payload.call_log_id);
        });
        actions.querySelector("[data-action=accept]").addEventListener("click", function () {
            acceptCall(payload);
        });

        document.body.appendChild(wrap);
    }

    function showHud(payload) {
        // Floating "in call" widget with a hangup button.
        var hud = document.getElementById(HUD_ID);
        if (hud) hud.remove();
        hud = document.createElement("div");
        hud.id = HUD_ID;
        hud.style.position = "fixed";
        hud.style.top = "20px";
        hud.style.right = "20px";
        hud.style.background = "#111827";
        hud.style.color = "#fff";
        hud.style.padding = "10px 14px";
        hud.style.borderRadius = "999px";
        hud.style.boxShadow = "0 6px 18px rgba(0,0,0,0.25)";
        hud.style.display = "flex";
        hud.style.alignItems = "center";
        hud.style.gap = "10px";
        hud.style.zIndex = "10000";
        hud.style.fontFamily = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
        hud.style.fontSize = "13px";
        hud.style.fontWeight = "600";
        hud.innerHTML =
            '<span style="width:8px;height:8px;background:#25D366;border-radius:50%;box-shadow:0 0 0 0 rgba(37,211,102,0.7);animation:wa-pulse 1.4s infinite;"></span>' +
            '<span>' + escapeHtml(payload.partner_name || "In call") + '</span>' +
            '<button data-action="hangup" style="background:#dc2626;color:#fff;border:none;border-radius:999px;width:28px;height:28px;font-weight:700;cursor:pointer;">✕</button>';
        var style = document.createElement("style");
        style.textContent = "@keyframes wa-pulse{0%{box-shadow:0 0 0 0 rgba(37,211,102,0.7);}70%{box-shadow:0 0 0 10px rgba(37,211,102,0);}100%{box-shadow:0 0 0 0 rgba(37,211,102,0);}}";
        hud.appendChild(style);
        hud.querySelector("[data-action=hangup]").addEventListener("click", function () {
            hangupCall(payload.call_log_id);
        });
        document.body.appendChild(hud);
    }

    function hideHud() {
        var hud = document.getElementById(HUD_ID);
        if (hud) hud.remove();
    }

    function escapeHtml(s) {
        return String(s || "")
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }

    // ── WebRTC pipeline ──────────────────────────────────────────────────
    function acceptCall(payload) {
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

        var call = { id: payload.call_log_id, pc: null, localStream: null, remoteStream: null, hangupSent: false };
        activeCall = call;

        // 1. Microphone.
        navigator.mediaDevices.getUserMedia({ audio: true, video: false })
            .then(function (stream) {
                call.localStream = stream;
                // 2. Peer connection.
                var pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
                call.pc = pc;

                pc.onicecandidate = function (ev) {
                    // Meta's Calling API is non-trickle — we hand over the
                    // full SDP once ICE gathering completes. Nothing to do
                    // per-candidate here.
                    if (!ev.candidate) log("ICE gathering complete");
                };
                pc.onconnectionstatechange = function () {
                    log("connection state:", pc.connectionState);
                    if (pc.connectionState === "failed" || pc.connectionState === "closed") {
                        teardownCall(false);
                    }
                };
                pc.oniceconnectionstatechange = function () {
                    log("ICE state:", pc.iceConnectionState);
                };
                pc.ontrack = function (ev) {
                    log("ontrack:", ev.streams && ev.streams[0]);
                    var audio = ensureRemoteAudioEl();
                    if (ev.streams && ev.streams[0]) {
                        audio.srcObject = ev.streams[0];
                        call.remoteStream = ev.streams[0];
                    }
                };

                // 3. Local tracks → PC.
                stream.getAudioTracks().forEach(function (t) { pc.addTrack(t, stream); });

                // 4. Remote offer → local answer.
                return pc.setRemoteDescription({ type: "offer", sdp: payload.sdp_offer })
                    .then(function () { return pc.createAnswer(); })
                    .then(function (answer) { return pc.setLocalDescription(answer); })
                    .then(function () { return waitForIceGathering(pc, 4000); });
            })
            .then(function () {
                // 5. Ship full SDP to server → Meta.
                return callRpc("/whatsapp/call/answer/" + call.id, {
                    sdp_answer: call.pc.localDescription.sdp,
                });
            })
            .then(function (result) {
                if (!result || !result.success) {
                    throw new Error((result && result.error) || "Accept failed");
                }
                notify("Call connected.", "success");
                showHud(payload);
            })
            .catch(function (err) {
                warn("accept failed:", err);
                notify("Accept failed: " + (err && err.message ? err.message : err), "danger");
                teardownCall(false);
            });
    }

    function waitForIceGathering(pc, timeoutMs) {
        if (pc.iceGatheringState === "complete") return Promise.resolve();
        return new Promise(function (resolve) {
            var done = false;
            function check() {
                if (done) return;
                if (pc.iceGatheringState === "complete") {
                    done = true;
                    pc.removeEventListener("icegatheringstatechange", check);
                    resolve();
                }
            }
            pc.addEventListener("icegatheringstatechange", check);
            setTimeout(function () {
                if (!done) {
                    done = true;
                    pc.removeEventListener("icegatheringstatechange", check);
                    resolve();
                }
            }, timeoutMs || 4000);
        });
    }

    function declineCall(callLogId) {
        hidePopup();
        callRpc("/whatsapp/call/decline/" + callLogId, {})
            .then(function () { notify("Call declined.", "info"); })
            .catch(function (err) {
                notify("Decline failed: " + (err && err.message ? err.message : err), "danger");
            });
    }

    function hangupCall(callLogId) {
        // Server-side hangup lives on the same route pattern (may be
        // added later). For now, tear down locally and let Meta detect
        // the peer disappearance via ICE failure.
        teardownCall(true);
        // Best-effort declines-as-hangup — Meta accepts "reject" on an
        // in-progress call to end it.
        callRpc("/whatsapp/call/decline/" + callLogId, {})
            .catch(function () {});
    }

    function teardownCall(userInitiated) {
        if (!activeCall) return;
        try { activeCall.pc && activeCall.pc.close(); } catch (e) {}
        try {
            (activeCall.localStream && activeCall.localStream.getTracks() || [])
                .forEach(function (t) { t.stop(); });
        } catch (e) {}
        var audio = document.getElementById(AUDIO_ID);
        if (audio) audio.srcObject = null;
        activeCall = null;
        hideHud();
        if (!userInitiated) notify("Call ended.", "info");
    }

    // ── Bus subscription ─────────────────────────────────────────────────
    function subscribeBus() {
        callRpc("/whatsapp/call/bus_channel", {})
            .then(function (info) {
                if (!info || !info.uid) return;
                // Odoo 18 bus service auto-adds channels by name for
                // authenticated users. The channel format matches what
                // whatsapp_webhook.py sends: (db, "whatsapp_incoming_call", uid).
                waitFor(function () {
                    return typeof odoo !== "undefined" && odoo.env
                        && odoo.env.services && odoo.env.services.bus_service;
                }, 8000).then(function (busService) {
                    try {
                        busService.subscribe("whatsapp_incoming_call", function (payload) {
                            handleBusEvent(payload);
                        });
                        busService.start && busService.start();
                        log("bus subscribed");
                    } catch (e) {
                        warn("bus subscribe failed:", e);
                    }
                }).catch(function () {
                    warn("bus_service never appeared");
                });
            })
            .catch(function (err) {
                warn("bus_channel RPC failed:", err);
            });
    }

    function waitFor(pred, timeoutMs) {
        return new Promise(function (resolve, reject) {
            var t0 = Date.now();
            (function tick() {
                var v = pred();
                if (v) return resolve(v);
                if (Date.now() - t0 > timeoutMs) return reject(new Error("timeout"));
                setTimeout(tick, 200);
            })();
        });
    }

    function handleBusEvent(payload) {
        if (!payload || !payload.type) return;
        if (payload.type === "whatsapp_incoming_call") {
            showPopup(payload);
        }
    }

    // Kick off on DOM ready.
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", subscribeBus);
    } else {
        subscribeBus();
    }
})();
