/** @odoo-module **/

import { registry } from "@web/core/registry";

export function restrictNumericInput() {
    const numericFields = ["bb_sales", "bb_returns", "puer_sales", "puer_returns"];

    // 👉 Restrict input to numbers and one dot
    function enforceNumericInput(event) {
        const target = event.target;
        let fieldName = target.getAttribute("data-name") || target.name;

        if (!fieldName || fieldName === "o_input") {
            const parentTd = target.closest("td");
            if (parentTd) {
                fieldName = parentTd.getAttribute("data-name") || parentTd.getAttribute("name");
            }
        }

        if (numericFields.includes(fieldName)) {
            let value = target.value;
            let filteredValue = value.replace(/[^0-9.]/g, "");

            const parts = filteredValue.split(".");
            if (parts.length > 2) {
                filteredValue = parts[0] + "." + parts.slice(1).join("");
            }

            if (value !== filteredValue) {
                target.value = filteredValue;
            }
        }
    }

    // 👉 Handle Numpad + (Tab) and Numpad - (Shift+Tab)
    function handleCustomKeyNavigation(event) {
        const target = event.target;

        if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) return;

        const tabbables = Array.from(document.querySelectorAll(
            'input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )).filter(el => el.offsetParent !== null); // ignore hidden

        const currentIndex = tabbables.indexOf(target);

        if (event.code === "NumpadAdd") {
            event.preventDefault();
            const next = tabbables[currentIndex + 1];
            if (next) next.focus();
        }

        if (event.code === "NumpadSubtract") {
            event.preventDefault();
            const prev = tabbables[currentIndex - 1];
            if (prev) prev.focus();
        }
    }

    function applyRestrictionsToExistingFields() {
        document.querySelectorAll("input").forEach((input) => {
            if (numericFields.includes(input.getAttribute("name"))) {
                input.removeEventListener("input", enforceNumericInput);
                input.addEventListener("input", enforceNumericInput);
            }
        });
    }

    function setupObserver() {
        const observer = new MutationObserver(() => {
            applyRestrictionsToExistingFields();
        });

        observer.observe(document.body, { childList: true, subtree: true });
        applyRestrictionsToExistingFields();
    }

    function init() {
        if (!document.body) {
            console.warn("document.body is not available. Retrying in 100ms...");
            setTimeout(init, 100);
            return;
        }

        document.addEventListener("input", enforceNumericInput, true);
        document.addEventListener("keydown", handleCustomKeyNavigation, true); // 👉 Add key listener
        setupObserver();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
}

// Register on web.boot
registry.category("web.boot").add("restrict_numeric_input", restrictNumericInput);
restrictNumericInput();