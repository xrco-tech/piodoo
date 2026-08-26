/** @odoo-module **/
/**
 * WhatsApp call monitoring — Phase 1: Listen (silent).
 *
 * WhatsApp calls are browser<->Meta WebRTC, so a supervisor can't be spied on
 * the server. Instead this opens a SECOND WebRTC connection agent<->supervisor:
 * the agent's browser relays a mix of both call legs; the supervisor just plays
 * it. Signalling rides the Odoo bus; NAT traversal uses coturn (ICE servers
 * from /whatsapp/monitor/ice_servers).
 *
 * Roles per browser:
 *   - AGENT (owns the call): on 'wa_monitor_request' for our active call, send
 *     an SDP offer with the mixed audio (send-only).
 *   - SUPERVISOR (initiated): on 'wa_monitor_start', wait for the offer, answer,
 *     and play the incoming audio.
 */
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";

export const waCallMonitorService = {
    dependencies: ["bus_service", "orm", "comm_whatsapp_calling", "notification"],
    start(env, { bus_service, orm, comm_whatsapp_calling, notification }) {
        const monitors = {}; // monitor_id -> { pc, role, ctx, audioEl, remotePartnerId, pendingIce }
        const log = (...a) => console.debug("[wa-monitor]", ...a);

        async function iceServers() {
            try {
                const r = await fetch("/whatsapp/monitor/ice_servers", {
                    method: "POST", credentials: "same-origin",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: {} }),
                });
                const j = await r.json();
                return (j.result && j.result.iceServers) || [{ urls: ["stun:stun.l.google.com:19302"] }];
            } catch (e) {
                log("ice fetch failed, using public STUN", e);
                return [{ urls: ["stun:stun.l.google.com:19302"] }];
            }
        }

        async function sendSignal(monitorId, toPartnerId, kind, data) {
            try {
                await fetch("/whatsapp/monitor/signal", {
                    method: "POST", credentials: "same-origin",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        jsonrpc: "2.0", method: "call",
                        params: { monitor_id: monitorId, to_partner_id: toPartnerId, kind, data },
                    }),
                });
            } catch (e) {
                log("signal send failed", kind, e);
            }
        }

        function teardown(monitorId) {
            const m = monitors[monitorId];
            if (!m) return;
            try { m.pc && m.pc.close(); } catch (e) { /* */ }
            try { m.ctx && m.ctx.close(); } catch (e) { /* */ }
            try { m.audioEl && m.audioEl.remove(); } catch (e) { /* */ }
            delete monitors[monitorId];
            log("monitor", monitorId, "torn down");
        }

        // ── AGENT side ────────────────────────────────────────────────────
        async function onRequest(p) {
            if (!p || comm_whatsapp_calling.getActiveCallId() !== p.call_log_id) {
                return; // not our call
            }
            const mix = comm_whatsapp_calling.buildMonitorMix(p.call_log_id);
            if (!mix) return;
            const pc = new RTCPeerConnection({ iceServers: await iceServers() });
            monitors[p.monitor_id] = {
                pc, role: "agent", ctx: mix.ctx, remotePartnerId: p.supervisor_partner_id,
            };
            mix.stream.getAudioTracks().forEach((t) => pc.addTrack(t, mix.stream)); // send-only
            pc.onicecandidate = (e) => {
                if (e.candidate) sendSignal(p.monitor_id, p.supervisor_partner_id, "ice", e.candidate.toJSON());
            };
            const offer = await pc.createOffer();
            await pc.setLocalDescription(offer);
            await sendSignal(p.monitor_id, p.supervisor_partner_id, "offer",
                { sdp: pc.localDescription, from_partner_id: user.partnerId });
            orm.call("comm.whatsapp.monitor", "mark_active", [p.monitor_id]).catch(() => {});
            log("agent: offer sent for monitor", p.monitor_id);
        }

        // ── SUPERVISOR side ───────────────────────────────────────────────
        function onStart(p) {
            monitors[p.monitor_id] = { pc: null, role: "supervisor", callLogId: p.call_log_id, pendingIce: [] };
            log("supervisor: awaiting offer for monitor", p.monitor_id);
        }

        async function onSignal(p) {
            const m = monitors[p.monitor_id];
            if (!m) return;
            if (p.kind === "offer" && m.role === "supervisor") {
                const pc = new RTCPeerConnection({ iceServers: await iceServers() });
                m.pc = pc;
                m.remotePartnerId = p.data.from_partner_id;
                pc.onicecandidate = (e) => {
                    if (e.candidate) sendSignal(p.monitor_id, m.remotePartnerId, "ice", e.candidate.toJSON());
                };
                pc.ontrack = (e) => {
                    const stream = (e.streams && e.streams[0]) || new MediaStream([e.track]);
                    const el = document.createElement("audio");
                    el.autoplay = true;
                    el.srcObject = stream;
                    document.body.appendChild(el);
                    el.play().catch(() => {});
                    m.audioEl = el;
                    notification.add("Listening to the call.", { type: "info" });
                };
                await pc.setRemoteDescription(p.data.sdp);
                for (const c of m.pendingIce) { try { await pc.addIceCandidate(c); } catch (e) { /* */ } }
                m.pendingIce = [];
                const answer = await pc.createAnswer();
                await pc.setLocalDescription(answer);
                await sendSignal(p.monitor_id, m.remotePartnerId, "answer", { sdp: pc.localDescription });
                log("supervisor: answered monitor", p.monitor_id);
            } else if (p.kind === "answer" && m.role === "agent") {
                await m.pc.setRemoteDescription(p.data.sdp);
            } else if (p.kind === "ice") {
                if (m.pc && m.pc.remoteDescription) {
                    try { await m.pc.addIceCandidate(p.data); } catch (e) { /* */ }
                } else {
                    (m.pendingIce = m.pendingIce || []).push(p.data); // queue until remote set
                }
            }
        }

        function onStop(p) {
            teardown(p && p.monitor_id);
        }

        try {
            if (typeof bus_service.addChannel === "function") {
                bus_service.addChannel("wa_monitor_supervise");
            }
            bus_service.subscribe("wa_monitor_request", onRequest);
            bus_service.subscribe("wa_monitor_start", onStart);
            bus_service.subscribe("wa_monitor_signal", onSignal);
            bus_service.subscribe("wa_monitor_stop", onStop);
            log("call monitor ready");
        } catch (e) {
            console.warn("[wa-monitor] bus wiring failed:", e);
        }

        return {};
    },
};

registry.category("services").add("comm_whatsapp_calling_monitor", waCallMonitorService);
