/** @odoo-module **/

/**
 * Clio Cockpit — Enter-tangenten triggar sökning i RAG och Bibliotek.
 * Lyssnar på keydown i .o_field_widget[name="rag_query"] och
 * .o_field_widget[name="library_query"], klickar sedan på
 * närmaste .btn-primary i samma föräldrarad.
 */

const SEARCH_FIELDS = ["rag_query", "library_query"];

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

        // Gå upp till raden (o_row eller direkt förälder) och hitta sök-knappen
        const row =
            fieldWidget.closest(".o_cockpit_search_row") ||
            fieldWidget.closest(".o_row") ||
            fieldWidget.parentElement;

        const btn = row && row.querySelector("button.btn-primary");
        if (btn) btn.click();
    },
    true, // capture — fångar innan Odoo-hanterare
);
