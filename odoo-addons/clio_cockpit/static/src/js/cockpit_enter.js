/** @odoo-module **/

/**
 * Clio Cockpit — Enter-sökning + tab-persistens
 *
 * 1. Enter i rag_query / library_query triggar Sök-knappen
 * 2. Aktiv notebook-flik sparas i sessionStorage och återställs
 *    efter varje form-reload (MutationObserver på .o_notebook_headers)
 */

const SEARCH_FIELDS = ["rag_query", "library_query"];
const TAB_STORE_KEY = "clio_cockpit_active_tab";

// ── 1. Enter-sökning ─────────────────────────────────────────────────────────

document.addEventListener(
    "keydown",
    (ev) => {
        if (ev.key !== "Enter") return;

        const fieldWidget = ev.target.closest(".o_field_widget");
        if (!fieldWidget) return;

        const fieldName = fieldWidget.getAttribute("name");
        if (!SEARCH_FIELDS.includes(fieldName)) return;

        ev.preventDefault();
        ev.stopPropagation();

        const row =
            fieldWidget.closest(".o_cockpit_search_row") ||
            fieldWidget.closest(".o_row") ||
            fieldWidget.parentElement;

        const btn = row && row.querySelector("button.btn-primary");
        if (btn) btn.click();
    },
    true,
);

// ── 2. Tab-persistens ────────────────────────────────────────────────────────

function saveActiveTab() {
    const active = document.querySelector(".o_notebook_headers .nav-link.active");
    if (active) {
        sessionStorage.setItem(TAB_STORE_KEY, active.textContent.trim());
    }
}

function restoreActiveTab() {
    const saved = sessionStorage.getItem(TAB_STORE_KEY);
    if (!saved) return;
    const tabs = document.querySelectorAll(".o_notebook_headers .nav-link");
    for (const tab of tabs) {
        if (tab.textContent.trim() === saved && !tab.classList.contains("active")) {
            tab.click();
            break;
        }
    }
}

// Spara flik vid klick
document.addEventListener("click", (ev) => {
    if (ev.target.closest(".o_notebook_headers .nav-link")) {
        setTimeout(saveActiveTab, 50);
    }
}, true);

// Återställ flik när notebook renderas/uppdateras
const _observer = new MutationObserver(() => {
    if (document.querySelector(".o_notebook_headers")) {
        restoreActiveTab();
    }
});
_observer.observe(document.body, { childList: true, subtree: true });
