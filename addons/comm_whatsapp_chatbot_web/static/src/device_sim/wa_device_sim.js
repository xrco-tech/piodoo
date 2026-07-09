/** @odoo-module **/

/**
 * Patches comm_whatsapp_chatbot's ChatbotFlowAction to add a device
 * simulator tab. The XML template inherit (wa_device_sim.xml) adds the
 * tab button and body; the patch below adds the state + helper methods.
 */
import { patch } from "@web/core/utils/patch";
import { ChatbotFlowAction } from "@comm_whatsapp_chatbot/js/chatbot_flow_widget";

const DEVICES = [
    { key: "iphone",  label: "iPhone",  cssClass: "o_wa_device_iphone"  },
    { key: "pixel",   label: "Pixel",   cssClass: "o_wa_device_pixel"   },
    { key: "ipad",    label: "iPad",    cssClass: "o_wa_device_ipad"    },
    { key: "desktop", label: "Desktop", cssClass: "o_wa_device_desktop" },
];

patch(ChatbotFlowAction.prototype, {
    setup() {
        super.setup(...arguments);
        this.state.deviceSim = { active: "iphone" };
    },

    _deviceList() { return DEVICES; },

    _pickWaDevice(key) {
        this.state.deviceSim.active = key;
    },

    _activeWaDevice() {
        return DEVICES.find(d => d.key === (this.state.deviceSim
                                              && this.state.deviceSim.active))
                || DEVICES[0];
    },

    _waDeviceEmbedUrl() {
        const chatbotId = this.state.chatbotId || this.state.chatbot_id
                          || (this.props.action.context.active_id || 0);
        if (!chatbotId) return "";
        return `/comm_whatsapp_chatbot_web/embed/${chatbotId}?preview=1&_ts=${Date.now()}`;
    },
});

// The template inherit is loaded via assets bundle; nothing else to register.
