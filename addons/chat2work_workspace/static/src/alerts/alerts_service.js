/** @odoo-module **/

import { reactive } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";

const WS = "chat2work.workspace";
const LIVE_CHANNEL = "chat2work_workspace";
const LIVE_TYPE = "chat2work_workspace/changed";
const WORKSPACE_ACTION = "chat2work_workspace.action_chat2work_workspace";
const SOUND_KEY = "chat2work_alerts.sound";
// The bot answers most messages itself within the same request. Waiting a moment
// before asking who is waiting keeps those from raising an alert.
const SETTLE_MS = 3000;
const EVERY_MS = 60000;
// More than this many at once are announced as one alert.
const ONE_BY_ONE = 2;

function stored(key) {
    try {
        return browser.localStorage.getItem(key);
    } catch {
        return null;
    }
}

function desktopState() {
    return "Notification" in window ? Notification.permission : "unsupported";
}

/**
 * Alerts for Chat2Work agents on every Odoo screen: who is waiting, and a
 * pop-up, a sound and (if the agent allowed it) a desktop notification for each
 * new one. The server's live notice carries no details, so anything shown comes
 * from the agent-only `ws_alerts` call.
 */
export const chat2workAlertsService = {
    dependencies: ["bus_service", "orm", "notification", "action", "multi_tab"],

    start(env, { bus_service, orm, notification, action, multi_tab }) {
        const state = reactive({
            agent: false,
            count: 0,
            counts: { reply: 0, callback: 0, unknown: 0 },
            items: [],
            sound: stored(SOUND_KEY) !== "off",
            desktop: desktopState(),
        });
        let seen = null; // keys already known; null until the first load, which alerts on nothing
        let settle = null;
        let audio = null;
        let workspace = null; // the open Workspace's "show this" function
        let pending = null; // what a Workspace that is about to open should show

        function chime() {
            try {
                const Ctx = window.AudioContext || window.webkitAudioContext;
                audio = audio || new Ctx();
                if (audio.state === "suspended") {
                    audio.resume();
                }
                [880, 1175].forEach((frequency, index) => {
                    const start = audio.currentTime + index * 0.16;
                    const tone = audio.createOscillator();
                    const volume = audio.createGain();
                    tone.type = "sine";
                    tone.frequency.value = frequency;
                    volume.gain.setValueAtTime(0.0001, start);
                    volume.gain.exponentialRampToValueAtTime(0.18, start + 0.02);
                    volume.gain.exponentialRampToValueAtTime(0.0001, start + 0.4);
                    tone.connect(volume).connect(audio.destination);
                    tone.start(start);
                    tone.stop(start + 0.42);
                });
            } catch {
                // No sound in this browser, or it hasn't been clicked in yet: the pop-up still shows.
            }
        }

        async function desktop(title, body, tag, target) {
            if (desktopState() !== "granted") {
                return;
            }
            const options = { body, tag, icon: "/chat2work_workspace/static/description/icon.png" };
            try {
                const note = new Notification(title, options);
                note.onclick = () => {
                    window.focus();
                    open(target);
                    note.close();
                };
            } catch {
                // Phones only allow notifications through the page's service worker.
                const registration = await navigator.serviceWorker?.getRegistration();
                await registration?.showNotification(title, options);
            }
        }

        /** Show a candidate, a number or a list in the Workspace, opening it if needed. */
        function open(target) {
            if (workspace) {
                return workspace(target);
            }
            pending = target;
            return action.doAction(WORKSPACE_ACTION, { clearBreadcrumbs: true });
        }

        function targetOf(item) {
            return item.candidate_id ? { candidate_id: item.candidate_id } : { unknown: item.wa_id };
        }

        async function announce(fresh) {
            const alerts = fresh.length > ONE_BY_ONE
                ? [{
                    title: _t("%s people are waiting", fresh.length),
                    text: fresh.slice(0, 3).map((item) => item.name).join(", ") + (fresh.length > 3 ? "…" : ""),
                    key: "many",
                    target: { pill: "reply" },
                }]
                : fresh.map((item) => ({ title: item.name, text: item.text, key: item.key, target: targetOf(item) }));
            const looking = document.visibilityState === "visible" && document.hasFocus();
            // An agent already on the Workspace sees the message arrive there; the sound is enough.
            if (!(workspace && looking)) {
                for (const alert of alerts) {
                    notification.add(alert.text, {
                        title: alert.title,
                        type: "info",
                        buttons: [{ name: _t("Open"), primary: true, onClick: () => open(alert.target) }],
                    });
                }
            }
            // One tab speaks for all of them.
            if (!(await multi_tab.isOnMainTab())) {
                return;
            }
            if (state.sound) {
                chime();
            }
            if (!looking) {
                for (const alert of alerts) {
                    desktop(alert.title, alert.text, "chat2work-" + alert.key, alert.target);
                }
            }
        }

        async function refresh() {
            let data;
            try {
                data = await orm.silent.call(WS, "ws_alerts", []);
            } catch {
                return; // offline or signed out; the next round tries again
            }
            Object.assign(state, { count: data.count, counts: data.counts, items: data.items });
            const first = seen === null;
            seen = seen || new Set();
            const fresh = data.items.filter((item) => !seen.has(item.key));
            fresh.forEach((item) => seen.add(item.key));
            if (!first && fresh.length) {
                await announce(fresh);
            }
        }

        function onNotice() {
            browser.clearTimeout(settle);
            settle = browser.setTimeout(refresh, SETTLE_MS);
        }

        user.hasGroup("chat2work.group_agent").then((agent) => {
            if (!agent) {
                return;
            }
            state.agent = true;
            bus_service.addChannel(LIVE_CHANNEL);
            bus_service.subscribe(LIVE_TYPE, onNotice);
            browser.setInterval(refresh, EVERY_MS);
            document.addEventListener("visibilitychange", () => document.visibilityState === "visible" && onNotice());
            refresh();
        });

        return {
            state,
            refresh,
            open,
            targetOf,
            /** The Workspace registers itself while it is on screen. */
            attach(show) {
                workspace = show;
            },
            detach(show) {
                if (workspace === show) {
                    workspace = null;
                }
            },
            /** What the Workspace should show as it opens, if an alert asked for something. */
            takePending() {
                const target = pending;
                pending = null;
                return target;
            },
            setSound(on) {
                state.sound = on;
                try {
                    browser.localStorage.setItem(SOUND_KEY, on ? "on" : "off");
                } catch {
                    // Kept for this page only.
                }
                if (on) {
                    chime();
                }
            },
            /** Ask the browser for desktop notifications. Has to come from a click. */
            async askDesktop() {
                if (!("Notification" in window)) {
                    return;
                }
                try {
                    await Notification.requestPermission();
                } catch {
                    // Older browsers answer through a callback; the state below is still right.
                }
                state.desktop = desktopState();
                if (state.desktop === "granted") {
                    desktop(_t("Chat2Work"), _t("Desktop notifications are on."), "chat2work-test", {});
                }
            },
        };
    },
};

registry.category("services").add("chat2work_alerts", chat2workAlertsService);
