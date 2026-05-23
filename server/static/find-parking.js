(function () {
    const debounce = (fn, ms) => {
        let t;
        return (...args) => {
            clearTimeout(t);
            t = setTimeout(() => fn(...args), ms);
        };
    };

    function buildQueryUrl(base, params) {
        const url = new URL(base, window.location.origin);
        Object.entries(params).forEach(([k, v]) => {
            if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
        });
        return url.pathname + url.search;
    }

    function initMap(cfg) {
        const container = document.getElementById("rental-map");
        const loading = document.getElementById("rental-map-loading");
        const center = cfg.searchCenter;
        const markers = (cfg.listings || []).map((m) => ({
            lat: m.lat,
            lng: m.lng,
            title: m.title,
            subtitle: `${m.instantDisplay} ${cfg.currencyName}/h · ${m.distanceKm} km`,
            status: m.status || "empty",
            listingId: m.listingId,
            actionHtml: `<button type="button" class="btn btn-sm btn-primary fp-map-book-btn" data-listing-id="${m.listingId}">Book &amp; pay</button>`,
        }));

        if (!center || !window.SpotflowMaps) {
            if (loading) loading.textContent = "Search a place to see parking spots";
            return;
        }

        if (!markers.length) {
            if (loading) loading.textContent = "No spots with map coordinates in this area";
        }

        SpotflowMaps.render("rental-map", markers, {
            fitBounds: true,
            padding: [56, 56],
            maxZoom: 15,
            destination: {
                lat: center.lat,
                lng: center.lng,
                label: center.label,
                color: "#64D2FF",
            },
            radiusKm: cfg.radiusKm,
            onReady: () => loading?.remove(),
        }).catch(() => {
            if (loading) loading.textContent = "Map unavailable";
        });

        container?.addEventListener("click", (e) => {
            const btn = e.target.closest(".fp-map-book-btn");
            if (!btn) return;
            const id = parseInt(btn.dataset.listingId, 10);
            if (id) openBookModal(cfg, id);
        });
    }

    function openBookModal(cfg, listingId) {
        const listing = (cfg.listings || []).find((l) => l.listingId === listingId);
        const modal = document.getElementById("fp-book-modal");
        const title = document.getElementById("fp-book-title");
        const subtitle = document.getElementById("fp-book-subtitle");
        const listingInput = document.getElementById("fp-book-listing-id");
        const hoursInput = document.getElementById("fp-book-hours");
        const totalLine = document.getElementById("fp-book-total-line");
        if (!modal || !listing) return;

        listingInput.value = listingId;
        title.textContent = listing.title;
        subtitle.textContent = `${listing.subtitle} · ${listing.distanceKm} km away · ${listing.instantDisplay} ${cfg.currencyName}/h`;

        const updateTotal = () => {
            const hours = Math.max(1, parseInt(hoursInput.value, 10) || 1);
            const hundredths = listing.instantHundredths * hours;
            const spots = Math.ceil(hundredths / 100);
            totalLine.textContent = `Total: ${spots} ${cfg.currencyName} (${hours}h × ${listing.instantDisplay}/h, rounded up)`;
        };
        hoursInput.removeEventListener("input", hoursInput._fpTotalHandler);
        hoursInput._fpTotalHandler = updateTotal;
        hoursInput.addEventListener("input", updateTotal);
        updateTotal();

        const form = document.getElementById("fp-book-form");
        if (form && cfg.searchCenter) {
            form.action = window.location.pathname + window.location.search;
        }

        modal.hidden = false;
        modal.setAttribute("aria-hidden", "false");
    }

    function closeBookModal() {
        const modal = document.getElementById("fp-book-modal");
        if (!modal) return;
        modal.hidden = true;
        modal.setAttribute("aria-hidden", "true");
    }

    function showConfirmation(cfg) {
        const data = cfg.bookingConfirmation;
        if (!data) return;

        const modal = document.getElementById("fp-confirm-modal");
        const body = document.getElementById("fp-confirm-body");
        const details = document.getElementById("fp-confirm-details");
        const title = document.getElementById("fp-confirm-title");
        if (!modal || !body) return;

        const pending = data.status === "pending_approval";
        title.textContent = pending ? "Payment received — pending approval" : "Booking confirmed";
        body.textContent = pending
            ? "Your payment is reserved. The spot owner will confirm shortly."
            : "You're all set. Your plate is authorized for this spot during your booking.";

        const rows = [
            ["Spot", data.spot],
            ["Plate", data.plate],
            ["Paid", `${data.total} ${cfg.currencyName}`],
        ];
        if (data.hours) rows.push(["Duration", `${data.hours} hour(s)`]);
        if (data.starts && data.ends) rows.push(["When", `${data.starts} – ${data.ends}`]);
        rows.push(["Status", data.status.replace(/_/g, " ")]);

        details.innerHTML = rows
            .map(([k, v]) => `<li><span class="text-secondary">${k}</span> <strong>${v}</strong></li>`)
            .join("");

        modal.hidden = false;
        modal.setAttribute("aria-hidden", "false");

        const cleanUrl = new URL(window.location.href);
        ["booking_ok", "booking_spot", "booking_plate", "booking_total", "booking_hours", "booking_status", "booking_type", "booking_starts", "booking_ends"].forEach((k) =>
            cleanUrl.searchParams.delete(k)
        );
        window.history.replaceState({}, "", cleanUrl.pathname + cleanUrl.search);
    }

    function wireSearch(cfg) {
        const input = document.getElementById("fp-search-input");
        const lat = document.getElementById("fp-lat");
        const lng = document.getElementById("fp-lng");
        const radius = document.getElementById("fp-radius");
        const box = document.getElementById("fp-suggestions");
        const form = document.getElementById("fp-search-form");
        if (!input || !box || !form) return;

        let activeIndex = -1;
        let lastResults = [];

        const navigateSearch = (row) => {
            input.value = row.label;
            if (lat) lat.value = row.lat;
            if (lng) lng.value = row.lng;
            if (radius && !radius.value) radius.value = cfg.radiusKm;
            box.hidden = true;
            input.setAttribute("aria-expanded", "false");
            const params = {
                q: row.label,
                lat: row.lat,
                lng: row.lng,
                max_distance: radius?.value || cfg.radiusKm,
            };
            window.location.href = buildQueryUrl(form.action, params);
        };

        const renderSuggestions = (results) => {
            lastResults = results;
            activeIndex = -1;
            box.innerHTML = "";
            if (!results.length) {
                box.hidden = true;
                input.setAttribute("aria-expanded", "false");
                return;
            }
            results.forEach((row, idx) => {
                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = "fp-suggestion-item";
                btn.setAttribute("role", "option");
                btn.id = `fp-sug-${idx}`;
                btn.innerHTML = `<span class="fp-suggestion-pin" aria-hidden="true"></span><span>${row.label}</span>`;
                btn.addEventListener("mousedown", (e) => {
                    e.preventDefault();
                    navigateSearch(row);
                });
                box.appendChild(btn);
            });
            box.hidden = false;
            input.setAttribute("aria-expanded", "true");
        };

        const fetchSuggestions = debounce(async () => {
            const q = input.value.trim();
            if (q.length < 2) {
                box.hidden = true;
                box.innerHTML = "";
                return;
            }
            try {
                const res = await fetch(`/portal/api/geocode?q=${encodeURIComponent(q)}&limit=8`);
                const data = await res.json();
                renderSuggestions(data.results || []);
            } catch (_e) {
                box.hidden = true;
            }
        }, 120);

        input.addEventListener("input", fetchSuggestions);
        input.addEventListener("focus", () => {
            if (input.value.trim().length >= 2 && lastResults.length) {
                box.hidden = false;
                input.setAttribute("aria-expanded", "true");
            }
        });

        input.addEventListener("keydown", (e) => {
            if (!lastResults.length || box.hidden) return;
            if (e.key === "ArrowDown") {
                e.preventDefault();
                activeIndex = Math.min(activeIndex + 1, lastResults.length - 1);
            } else if (e.key === "ArrowUp") {
                e.preventDefault();
                activeIndex = Math.max(activeIndex - 1, 0);
            } else if (e.key === "Enter" && activeIndex >= 0) {
                e.preventDefault();
                navigateSearch(lastResults[activeIndex]);
                return;
            } else if (e.key === "Escape") {
                box.hidden = true;
                return;
            } else {
                return;
            }
            box.querySelectorAll(".fp-suggestion-item").forEach((el, i) => {
                el.classList.toggle("is-active", i === activeIndex);
            });
        });

        form.addEventListener("submit", (e) => {
            if (!lat?.value || !lng?.value) {
                e.preventDefault();
                if (lastResults.length) {
                    navigateSearch(lastResults[0]);
                } else {
                    input.focus();
                }
            } else if (radius && !radius.value) {
                radius.value = cfg.radiusKm;
            }
        });

        document.addEventListener("click", (e) => {
            if (!box.contains(e.target) && e.target !== input) {
                box.hidden = true;
                input.setAttribute("aria-expanded", "false");
            }
        });
    }

    function wireModals(cfg) {
        document.getElementById("fp-book-close")?.addEventListener("click", closeBookModal);
        document.getElementById("fp-book-modal")?.addEventListener("click", (e) => {
            if (e.target.id === "fp-book-modal") closeBookModal();
        });
        document.getElementById("fp-confirm-done")?.addEventListener("click", () => {
            const modal = document.getElementById("fp-confirm-modal");
            if (modal) {
                modal.hidden = true;
                modal.setAttribute("aria-hidden", "true");
            }
        });

        document.querySelectorAll("[data-fp-scroll]").forEach((btn) => {
            btn.addEventListener("click", () => {
                const id = btn.getAttribute("data-fp-scroll");
                document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
            });
        });
    }

    function init(cfg) {
        cfg = cfg || {};
        wireSearch(cfg);
        wireModals(cfg);
        initMap(cfg);
        showConfirmation(cfg);
    }

    window.SpotflowFindParking = { init, openBookModal };
})();
