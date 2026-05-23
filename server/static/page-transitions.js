(function () {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const root = document.documentElement;
    const supportsCrossDocVT =
        typeof CSS !== "undefined" &&
        CSS.supports("view-transition-name", "none") &&
        document.querySelector('meta[name="view-transition"]');

    function isInternalNavLink(anchor) {
        if (!anchor || anchor.target === "_blank" || anchor.hasAttribute("download")) return false;
        if (anchor.origin !== window.location.origin) return false;
        const href = anchor.getAttribute("href");
        if (!href || href.startsWith("#") || href.startsWith("javascript:")) return false;
        if (anchor.dataset.noTransition === "true") return false;
        return true;
    }

    function playEnter() {
        if (reduced) return;
        root.classList.add("pw-page-enter");
        requestAnimationFrame(() => {
            requestAnimationFrame(() => root.classList.remove("pw-page-enter"));
        });
    }

    function leaveThenGo(url) {
        root.classList.add("pw-page-leaving");
        window.setTimeout(() => {
            window.location.href = url;
        }, 220);
    }

    document.addEventListener("click", (event) => {
        if (event.defaultPrevented || event.button !== 0) return;
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        const anchor = event.target.closest("a[href]");
        if (!isInternalNavLink(anchor)) return;

        if (reduced) return;

        if (supportsCrossDocVT) {
            root.classList.add("pw-page-leaving");
            return;
        }

        event.preventDefault();
        leaveThenGo(anchor.href);
    });

    document.addEventListener("submit", (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) return;
        if (form.target === "_blank" || form.dataset.noTransition === "true") return;
        if (form.dataset.confirm && form.dataset.confirmed !== "true") return;
        if (reduced) return;
        root.classList.add("pw-page-leaving");
    });

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", playEnter);
    } else {
        playEnter();
    }
})();
