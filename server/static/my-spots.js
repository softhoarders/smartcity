(function () {
    function initSettingsModal() {
        const backdrop = document.getElementById("ms-settings-modal");
        if (!backdrop) return;

        const closeBtn = backdrop.querySelector("[data-ms-close]");
        const panels = backdrop.querySelectorAll("[data-ms-panel]");
        let activePanel = null;

        function closeModal() {
            backdrop.hidden = true;
            backdrop.setAttribute("aria-hidden", "true");
            document.body.classList.remove("ms-modal-open");
            panels.forEach((p) => {
                p.hidden = true;
            });
            activePanel = null;
        }

        function openModal(deviceId) {
            const panel = backdrop.querySelector(`[data-ms-panel="${deviceId}"]`);
            if (!panel) return;
            panels.forEach((p) => {
                p.hidden = p !== panel;
            });
            activePanel = panel;
            backdrop.hidden = false;
            backdrop.setAttribute("aria-hidden", "false");
            document.body.classList.add("ms-modal-open");
            panel.querySelector(".ms-settings-panel")?.focus?.();
        }

        document.querySelectorAll("[data-ms-settings]").forEach((btn) => {
            btn.addEventListener("click", (e) => {
                e.preventDefault();
                e.stopPropagation();
                const deviceId = btn.getAttribute("data-ms-settings");
                if (deviceId) openModal(deviceId);
            });
        });

        closeBtn?.addEventListener("click", closeModal);
        backdrop.addEventListener("click", (e) => {
            if (e.target === backdrop) closeModal();
        });
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape" && !backdrop.hidden) closeModal();
        });

        const hash = window.location.hash;
        if (hash.startsWith("#spot-")) {
            openModal(hash.replace("#spot-", ""));
        }
    }

    async function registerPush() {
        if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;
        if (localStorage.getItem("pw-push-enabled") !== "1") return;

        try {
            const reg = await navigator.serviceWorker.register("/static/sw.js");
            let sub = await reg.pushManager.getSubscription();
            if (!sub) {
                const response = await fetch("/api/push/public-key");
                if (!response.ok) return;
                const { publicKey } = await response.json();
                if (!publicKey) return;
                sub = await reg.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: urlBase64ToUint8Array(publicKey),
                });
            }
            await fetch("/api/push/subscribe", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(sub),
            });
        } catch (err) {
            console.warn("[MySpots] push registration skipped", err);
        }
    }

    function urlBase64ToUint8Array(base64String) {
        const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
        const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
        const rawData = window.atob(base64);
        const outputArray = new Uint8Array(rawData.length);
        for (let i = 0; i < rawData.length; ++i) {
            outputArray[i] = rawData.charCodeAt(i);
        }
        return outputArray;
    }

    function initPushConsent() {
        const consent = document.getElementById("ms-push-consent");
        if (!consent) return;
        if (!("Notification" in window) || !("PushManager" in window)) return;
        if (Notification.permission === "granted" || localStorage.getItem("pw-push-dismissed") === "1") {
            if (Notification.permission === "granted") registerPush();
            return;
        }
        consent.hidden = false;
        document.getElementById("ms-push-enable")?.addEventListener("click", async () => {
            const perm = await Notification.requestPermission();
            if (perm === "granted") {
                localStorage.setItem("pw-push-enabled", "1");
                await registerPush();
            }
            consent.hidden = true;
        });
        document.getElementById("ms-push-dismiss")?.addEventListener("click", () => {
            localStorage.setItem("pw-push-dismissed", "1");
            consent.hidden = true;
        });
    }

    document.addEventListener("DOMContentLoaded", () => {
        initSettingsModal();
        initPushConsent();
        if (Notification?.permission === "granted") registerPush();
    });
})();
