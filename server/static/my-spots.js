(function () {
    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("[data-ms-spot-toggle]").forEach((btn) => {
            btn.addEventListener("click", () => {
                const panelId = btn.getAttribute("aria-controls");
                const panel = panelId ? document.getElementById(panelId) : null;
                if (!panel) return;
                const open = panel.hidden;
                panel.hidden = !open;
                btn.setAttribute("aria-expanded", open ? "true" : "false");
                btn.closest(".ms-spot-card")?.classList.toggle("is-open", open);
            });
        });
    });
})();
