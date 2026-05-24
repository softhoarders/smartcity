(function () {
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
                const avail = r.prediction_label || (r.available_now ? "Available now" : "Check availability");
                return `<div class="fp-concierge-result card border-0 mb-2">
                    <div class="card-body p-2">
                        <div class="fw-semibold small">${r.spot_label}</div>
                        <div class="text-secondary small">${r.name || ""} · ${r.distance_km ?? "—"} km · ${avail}</div>
                        <div class="small">${r.instant_display || "—"} ${cfg.currencyName}/h · ~${r.estimated_total_credits} ${cfg.currencyName} total</div>
                        <button type="button" class="btn btn-primary btn-sm mt-2 fp-concierge-book"
                            data-listing-id="${r.listing_id}"
                            data-intent='${JSON.stringify(intent).replace(/'/g, "&#39;")}'>Book this</button>
                    </div>
                </div>`;
            })
            .join("");
    }

    function init(cfg) {
        const form = document.getElementById("fp-concierge-form");
        const input = document.getElementById("fp-concierge-input");
        const log = document.getElementById("fp-concierge-log");
        if (!form || !input || !log) return;

        form.addEventListener("submit", async (e) => {
            e.preventDefault();
            const message = input.value.trim();
            if (!message) return;

            appendMessage(log, "user", `<p class="small mb-0">${message.replace(/</g, "&lt;")}</p>`);
            input.value = "";
            appendMessage(log, "assistant", `<p class="small mb-0 text-secondary">Searching…</p>`);

            try {
                const res = await fetch("/portal/api/concierge", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    credentials: "same-origin",
                    body: JSON.stringify({ message }),
                });
                const data = await res.json();
                log.lastChild?.remove();

                if (!res.ok || data.error) {
                    appendMessage(
                        log,
                        "assistant",
                        `<p class="small mb-0 text-danger">${(data.error || "Request failed").replace(/</g, "&lt;")}</p>`
                    );
                    return;
                }

                if (data.search_center && data.search_center.lat) {
                    appendMessage(
                        log,
                        "assistant",
                        `<p class="small mb-0">${(data.reply_text || "Updating map with matching spots…").replace(/</g, "&lt;")}</p>`
                    );
                    const url = new URL(window.location.pathname, window.location.origin);
                    url.searchParams.set("q", data.search_center.label || "");
                    url.searchParams.set("lat", data.search_center.lat);
                    url.searchParams.set("lng", data.search_center.lng);
                    if (data.intent && data.intent.arrive_at) {
                        const d = new Date(data.intent.arrive_at);
                        if (!Number.isNaN(d.getTime())) {
                            const pad = (n) => String(n).padStart(2, "0");
                            url.searchParams.set(
                                "target_at",
                                `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
                            );
                        }
                    }
                    window.location.href = url.pathname + url.search + "#concierge";
                } else {
                    const cards = buildResultCards(data.results || [], cfg, data.intent || {});
                    appendMessage(
                        log,
                        "assistant",
                        `<p class="small mb-2">${(data.reply_text || "Here are some options.").replace(/</g, "&lt;")}</p>${cards}`
                    );
                }
            } catch (_err) {
                log.lastChild?.remove();
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
            try {
                const res = await fetch("/portal/api/concierge/book", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    credentials: "same-origin",
                    body: JSON.stringify({ listing_id: listingId, intent, renter_plate: plate }),
                });
                const data = await res.json();
                if (data.ok && data.redirect_url) {
                    window.location.href = data.redirect_url;
                } else {
                    alert(data.error || "Booking failed.");
                }
            } catch (_err) {
                alert("Booking request failed.");
            }
        });
    }

    window.SpotflowConcierge = { init };
})();
