/** Incoming WhatsApp call popup – listens to bus and shows Accept/Decline dialog */

(function () {
    "use strict";

    var CHANNEL = "whatsapp_incoming_call";
    var POPUP_ID = "comm_whatsapp_calling_incoming_popup";

    function getBusService() {
        if (typeof odoo === "undefined") return null;
        try {
            if (odoo.__WOWL_DEBUG__ && odoo.__WOWL_DEBUG__.services && odoo.__WOWL_DEBUG__.services.bus_service) {
                return odoo.__WOWL_DEBUG__.services.bus_service;
            }
            if (odoo.env && odoo.env.services) {
                return odoo.env.services.bus_service || (odoo.env.services.get && odoo.env.services.get("bus_service"));
            }
        } catch (e) {}
        return null;
    }

    function hidePopup(callLogId) {
        var el = document.getElementById(POPUP_ID);
        if (el) el.remove();
        if (callLogId && window._waCallPopups) delete window._waCallPopups[callLogId];
    }

    function callRpc(url, params) {
        params = params || {};
        var body = JSON.stringify({
            jsonrpc: "2.0",
            method: "call",
            params: params,
            id: Math.floor(Math.random() * 1e9),
        });
        var csrfToken = document.querySelector('meta[name="csrf-token"]') && document.querySelector('meta[name="csrf-token"]').getAttribute("content");
        var headers = { "Content-Type": "application/json" };
        if (csrfToken) headers["X-CSRF-TOKEN"] = csrfToken;
        return fetch(url, {
            method: "POST",
            credentials: "same-origin",
            headers: headers,
            body: body,
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.error) throw new Error(data.error.data && data.error.data.message || data.error.message || "RPC error");
                return data.result;
            });
    }

    function acceptCall(callLogId, popupEl) {
        if (!callLogId) return;
        var btn = popupEl && popupEl.querySelector("[data-action=accept]");
        if (btn) { btn.disabled = true; btn.textContent = "Accepting…"; }
        callRpc("/whatsapp/call/answer/" + callLogId, {})
            .then(function () {
                hidePopup(callLogId);
                if (typeof odoo !== "undefined" && odoo.env && odoo.env.services && odoo.env.services.notification) {
                    odoo.env.services.notification.add("Call accepted.", { type: "success" });
                }
            })
            .catch(function (err) {
                if (btn) { btn.disabled = false; btn.textContent = "Accept"; }
                if (typeof odoo !== "undefined" && odoo.env && odoo.env.services && odoo.env.services.notification) {
                    odoo.env.services.notification.add("Accept failed: " + (err && err.message ? err.message : err), { type: "danger" });
                }
            });
    }

    function declineCall(callLogId, popupEl) {
        if (!callLogId) return;
        var btn = popupEl && popupEl.querySelector("[data-action=decline]");
        if (btn) { btn.disabled = true; btn.textContent = "Declining…"; }
        callRpc("/whatsapp/call/decline/" + callLogId, {})
            .then(function () {
                hidePopup(callLogId);
                if (typeof odoo !== "undefined" && odoo.env && odoo.env.services && odoo.env.services.notification) {
                    odoo.env.services.notification.add("Call declined.", { type: "info" });
                }
            })
            .catch(function (err) {
                if (btn) { btn.disabled = false; btn.textContent = "Decline"; }
                if (typeof odoo !== "undefined" && odoo.env && odoo.env.services && odoo.env.services.notification) {
                    odoo.env.services.notification.add("Decline failed: " + (err && err.message ? err.message : err), { type: "danger" });
                }
            });
    }

    function showPopup(payload) {
        var callLogId = payload.call_log_id;
        if (!callLogId) return;
        window._waCallPopups = window._waCallPopups || {};
        if (window._waCallPopups[callLogId]) {
            return;
        }
        window._waCallPopups[callLogId] = true;

        var fromLabel = payload.partner_name || payload.from_number || "Unknown";
        var timeLabel = payload.call_timestamp ? new Date(payload.call_timestamp).toLocaleString() : "";

        var popup = document.createElement("div");
        popup.id = POPUP_ID;
        popup.className = "o_comm_whatsapp_calling_popup";
        popup.innerHTML =
            '<div class="o_wa_popup_backdrop"></div>' +
            '<div class="o_wa_popup_box">' +
            '  <div class="o_wa_popup_header">' +
            '    <span class="o_wa_popup_title">Incoming WhatsApp call</span>' +
            '    <button type="button" class="o_wa_popup_close" aria-label="Close">&times;</button>' +
            '  </div>' +
            '  <div class="o_wa_popup_body">' +
            '    <p class="o_wa_popup_from"><strong>From:</strong> ' + (fromLabel.replace(/</g, "&lt;").replace(/>/g, "&gt;")) + '</p>' +
            (timeLabel ? '<p class="o_wa_popup_time"><strong>Time:</strong> ' + timeLabel + '</p>' : '') +
            '  </div>' +
            '  <div class="o_wa_popup_actions">' +
            '    <button type="button" class="btn btn-primary o_wa_btn_accept" data-action="accept">Accept</button>' +
            '    <button type="button" class="btn btn-secondary o_wa_btn_decline" data-action="decline">Decline</button>' +
            '  </div>' +
            '</div>';

        var box = popup.querySelector(".o_wa_popup_box");
        var closeBtn = popup.querySelector(".o_wa_popup_close");
        var acceptBtn = popup.querySelector("[data-action=accept]");
        var declineBtn = popup.querySelector("[data-action=decline]");
        var backdrop = popup.querySelector(".o_wa_popup_backdrop");

        function close() {
            hidePopup(callLogId);
        }

        closeBtn.addEventListener("click", close);
        backdrop.addEventListener("click", close);
        acceptBtn.addEventListener("click", function () { acceptCall(callLogId, box); });
        declineBtn.addEventListener("click", function () { declineCall(callLogId, box); });

        document.body.appendChild(popup);
    }

    function onNotification(notifications) {
        if (!Array.isArray(notifications)) notifications = [notifications];
        notifications.forEach(function (n) {
            var type = n.type || n.channel;
            var payload = n.payload !== undefined ? n.payload : (n.message !== undefined ? n.message : n.data || n);
            if (payload && payload.call_log_id && (type === CHANNEL || (payload && payload.type === CHANNEL))) {
                showPopup(payload);
            }
        });
    }

    function getSessionInfo() {
        var s = null;
        try {
            if (typeof odoo !== "undefined" && odoo.env && odoo.env.services) {
                s = odoo.env.services.session || (odoo.env.services.get && odoo.env.services.get("session"));
            }
            if (!s && typeof odoo !== "undefined" && odoo.__WOWL_DEBUG__ && odoo.__WOWL_DEBUG__.services) {
                s = odoo.__WOWL_DEBUG__.services.session;
            }
            if (s) {
                var db = s.db || s.db_name;
                var uid = s.uid !== undefined ? s.uid : (s.user_id !== undefined ? s.user_id : (s.user && s.user.user_id));
                if (db && uid !== undefined) return { db: db, uid: uid };
            }
        } catch (e) {}
        return null;
    }

    function addOurChannel(bus) {
        var session = getSessionInfo();
        if (session) {
            var channel = JSON.stringify([session.db, CHANNEL, session.uid]);
            if (typeof bus.addChannel === "function") {
                bus.addChannel(channel);
                return true;
            }
        }
        return false;
    }

    function setupBusListener() {
        var bus = getBusService();
        if (!bus || typeof bus.addEventListener !== "function") return false;
        addOurChannel(bus);
        bus.addEventListener("notification", function (event) {
            var detail = event.detail;
            if (detail) onNotification(Array.isArray(detail) ? detail : [detail]);
        });
        if (typeof bus.start === "function") bus.start();
        return true;
    }

    function trySetup() {
        if (setupBusListener()) return;
        setTimeout(trySetup, 500);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () { setTimeout(trySetup, 300); });
    } else {
        setTimeout(trySetup, 300);
    }
})();
