/** @odoo-module **/

(function () {
    try {
        // session_info is injected by Odoo server before any module runs
        const db = ((window.odoo && window.odoo.session_info && window.odoo.session_info.db) || "").toLowerCase();
        if (!db) return;

        const body = document.body;
        if (!body) return;

        if (db === "aiab") {
            body.classList.add("clio-db-aiab");
        } else if (db.startsWith("ssf")) {
            body.classList.add("clio-db-ssf");
        }

        if (/_test$|_demo$|_t\d+$/.test(db)) {
            body.classList.add("clio-env-test");
        } else if (/_staging$/.test(db)) {
            body.classList.add("clio-env-staging");
        }
    } catch (e) {
        // Never crash Odoo UI
    }
})();
