(function () {
    const LOADING_KEY = "spotflow_concierge_loading";

    function appendMessage(log, role, html) {
        const row = document.createElement("div");
        row.className = `fp-concierge-msg fp-concierge-msg--${role}`;
        row.innerHTML = html;
        log.appendChild(row);
        log.scrollTop = log.scrollHeight;
    }

    function buildResultCards(results, cfg, intent) {
        if (!results.length) return "<p class='small mb-0'>No matching spots found.</p>";
        return results
            .map((r) => {
                const route = r.route_label ? `${r.route_label} · ` : "";
                const avail = r.prediction_label || (r.available_now ? "Available now" : "Check availability");
                const trust = r.min_trust_score ? ` · trust ${r.min_trust_score}+` : "";
                return `<div class="fp-concierge-result card border-0 mb-2">
                    <div class="card-body p-2">
                        <div class="fw-semibold small">${r.spot_label}</div>
                        <div class="text-secondary small">${route}${r.name || ""} · ${r.distance_km ?? "—"} km · ${avail}${trust}</div>
                        <div class="small">${r.instant_display || "—"} ${cfg.currencyName}/h · ~${r.estimated_total_credits} ${cfg.currencyName} total</div>
                        <button type="button" class="btn btn-primary btn-sm mt-2 fp-concierge-book"
                            data-listing-id="${r.listing_id}"
                            data-intent='${JSON.stringify(intent).replace(/'/g, "&#39;")}'>Book this</button>
                    </div>
                </div>`;
            })
            .join("");
    }

    function csrfHeaders() {
        const token = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";
        const headers = { "Content-Type": "application/json" };
        if (token) headers["X-CSRF-Token"] = token;
        return headers;
    }

    function getLoadingEls() {
        return {
            panel: document.getElementById("concierge"),
            overlay: document.getElementById("fp-concierge-loading"),
            title: document.getElementById("fp-concierge-loading-title"),
            hint: document.getElementById("fp-concierge-loading-hint"),
            form: document.getElementById("fp-concierge-form"),
            input: document.getElementById("fp-concierge-input"),
            submit: document.getElementById("fp-concierge-send"),
        };
    }

    function showLoading(title, hint) {
        const { panel, overlay, title: titleEl, hint: hintEl, form, input, submit } = getLoadingEls();
        if (!panel || !overlay) return;

        if (titleEl && title) titleEl.textContent = title;
        if (hintEl && hint) hintEl.textContent = hint;

        panel.classList.add("is-loading");
        overlay.hidden = false;
        overlay.setAttribute("aria-hidden", "false");
        if (form) form.setAttribute("aria-busy", "true");
        if (input) input.disabled = true;
        if (submit) submit.disabled = true;
    }

    function hideLoading() {
        const { panel, overlay, form, input, submit } = getLoadingEls();
        if (!panel || !overlay) return;

        panel.classList.remove("is-loading");
        overlay.hidden = true;
        overlay.setAttribute("aria-hidden", "true");
        if (form) form.removeAttribute("aria-busy");
        if (input) input.disabled = false;
        if (submit) submit.disabled = false;
        try {
            sessionStorage.removeItem(LOADING_KEY);
        } catch (_e) {
            /* ignore */
        }
    }

    function resumeLoadingAfterNavigation() {
        try {
            if (sessionStorage.getItem(LOADING_KEY) !== "1") return false;
        } catch (_e) {
            return false;
        }
        showLoading("Updating map with matching spots", "Loading spots near your search…");
        window.setTimeout(hideLoading, 1200);
        return true;
    }

    async function parseJsonResponse(res) {
        const ct = res.headers.get("content-type") || "";
        if (!ct.includes("application/json")) {
            const text = await res.text();
            if (res.status === 400 && text.includes("CSRF")) {
                return { error: "Session expired. Refresh the page and try again." };
            }
            return { error: res.ok ? "Unexpected server response." : `Request failed (${res.status}).` };
        }
        return res.json();
    }

    function init(cfg) {
        const form = document.getElementById("fp-concierge-form");
        const input = document.getElementById("fp-concierge-input");
        const log = document.getElementById("fp-concierge-log");
        if (!form || !input || !log) return;

        resumeLoadingAfterNavigation();

        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                form.requestSubmit();
            }
        });

        form.addEventListener("submit", async (e) => {
            e.preventDefault();
            const message = input.value.trim();
            if (!message) return;

            appendMessage(log, "user", `<p class="small mb-0">${message.replace(/</g, "&lt;")}</p>`);
            input.value = "";
            showLoading("Searching for parking", "Understanding your request and finding nearby spots…");

            try {
                const res = await fetch("/portal/api/concierge", {
                    method: "POST",
                    headers: csrfHeaders(),
                    credentials: "same-origin",
                    body: JSON.stringify({ message }),
                });
                const data = await parseJsonResponse(res);

                if (!res.ok || data.error) {
                    hideLoading();
                    appendMessage(
                        log,
                        "assistant",
                        `<p class="small mb-0 text-danger">${(data.error || "Request failed").replace(/</g, "&lt;")}</p>`
                    );
                    return;
                }

                if (data.search_center && data.search_center.lat) {
                    showLoading("Updating map", "Placing your destination on the map…");
                    if (window.SpotflowFindParking?.applyConciergeSearch) {
                        window.SpotflowFindParking.applyConciergeSearch(
                            data.search_center,
                            data.results || [],
                            cfg
                        );
                    }
                    appendMessage(
                        log,
                        "assistant",
                        `<p class="small mb-0">${(data.reply_text || "Found spots near your destination.").replace(/</g, "&lt;")}</p>`
                    );
                    try {
                        sessionStorage.setItem(LOADING_KEY, "1");
                    } catch (_e) {
                        /* ignore */
                    }
                    const href = window.SpotflowFindParking?.buildConciergeUrl
                        ? window.SpotflowFindParking.buildConciergeUrl(data.search_center, data.intent || {})
                        : (() => {
                              const url = new URL(window.location.pathname, window.location.origin);
                              url.searchParams.set("q", data.search_center.label || "");
                              url.searchParams.set("lat", data.search_center.lat);
                              url.searchParams.set("lng", data.search_center.lng);
                              return url.pathname + url.search + "#concierge";
                          })();
                    window.setTimeout(() => {
                        window.location.href = href;
                    }, 500);
                    return;
                }

                hideLoading();
                const cards = buildResultCards(data.results || [], cfg, data.intent || {});
                appendMessage(
                    log,
                    "assistant",
                    `<p class="small mb-2">${(data.reply_text || "Here are some options.").replace(/</g, "&lt;")}</p>${cards}`
                );
            } catch (_err) {
                hideLoading();
                appendMessage(log, "assistant", `<p class="small mb-0 text-danger">Something went wrong. Try again.</p>`);
            }
        });

        log.addEventListener("click", async (e) => {
            const btn = e.target.closest(".fp-concierge-book");
            if (!btn) return;
            const listingId = parseInt(btn.dataset.listingId, 10);
            let intent = {};
            try {
                intent = JSON.parse(btn.dataset.intent || "{}");
            } catch (_e) {
                return;
            }
            if (!confirm("Confirm this booking? Your wallet will be charged if approved.")) return;

            const plate = (cfg.userPlates && cfg.userPlates[0]) || "";
            showLoading("Booking spot", "Confirming your reservation…");
            try {
                const res = await fetch("/portal/api/concierge/book", {
                    method: "POST",
                    headers: csrfHeaders(),
                    credentials: "same-origin",
                    body: JSON.stringify({ listing_id: listingId, intent, renter_plate: plate }),
                });
                const data = await parseJsonResponse(res);
                if (data.ok && data.redirect_url) {
                    try {
                        sessionStorage.setItem(LOADING_KEY, "1");
                    } catch (_e) {
                        /* ignore */
                    }
                    window.location.href = data.redirect_url;
                } else {
                    hideLoading();
                    alert(data.error || "Booking failed.");
                }
            } catch (_err) {
                hideLoading();
                alert("Booking request failed.");
            }
        });
    }

    window.SpotflowConcierge = { init };
})();
