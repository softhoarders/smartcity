(function () {
    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

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

    function pad2(n) {
        return String(n).padStart(2, "0");
    }

    function toDatetimeLocalValue(date) {
        return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}T${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
    }

    function parseDatetimeLocal(value) {
        if (!value) return null;
        const d = new Date(value);
        return Number.isNaN(d.getTime()) ? null : d;
    }

    function formatWhen(date) {
        return date.toLocaleString(undefined, {
            weekday: "short",
            day: "numeric",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
        });
    }

    function bookingHours(starts, ends) {
        if (!starts || !ends || ends <= starts) return 0;
        return Math.max(1, Math.floor((ends - starts) / 3600000) || 1);
    }

    function formatCreditsFromHundredths(hundredths) {
        const n = Math.max(0, Math.round(hundredths));
        const whole = Math.floor(n / 100);
        const frac = String(n % 100).padStart(2, "0");
        return `${whole}.${frac}`;
    }

    function billableCredits(hundredths) {
        return formatCreditsFromHundredths(hundredths);
    }

    function calcBookingQuote(listing, starts, ends) {
        const hours = bookingHours(starts, ends);
        if (!hours) {
            return { hours: 0, total: "0.00", totalHundredths: 0, valid: false };
        }
        const totalHundredths = (listing.rateHundredths || 0) * hours;
        return {
            hours,
            total: formatCreditsFromHundredths(totalHundredths),
            totalHundredths,
            valid: true,
        };
    }

    function defaultBookingRange() {
        const start = new Date();
        start.setMinutes(Math.ceil(start.getMinutes() / 15) * 15, 0, 0);
        start.setMinutes(start.getMinutes() + 30);
        const end = new Date(start);
        end.setHours(end.getHours() + 2);
        return { start, end };
    }

    function initMap(cfg) {
        const container = document.getElementById("rental-map");
        const loading = document.getElementById("rental-map-loading");
        const center = cfg.searchCenter;
        const STATUS_LABELS = {
            empty: "Empty",
            occupied: "Occupied",
            correct: "Registered",
            violation: "Violation",
            illegal: "Violation",
        };

        const markers = (cfg.listings || [])
            .filter((m) => m.lat != null && m.lng != null)
            .map((m) => {
                const statusGroup = m.statusGroup || (m.status === "illegal" ? "violation" : m.status);
                return {
                lat: m.lat,
                lng: m.lng,
                title: m.title,
                subtitle: `${m.routeLabel || (m.distanceKm + " km")}${m.predictionLabel ? " · " + m.predictionLabel : ""} · ${m.rateDisplay} ${cfg.currencyName}/h`,
                status: statusGroup,
                statusLabel: m.statusLabel || STATUS_LABELS[m.status] || m.status,
                listingId: m.listingId,
                actionHtml: `<button type="button" class="btn btn-sm btn-primary fp-map-book-btn" data-listing-id="${m.listingId}">Pay &amp; park</button>`,
            };
            });

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

    function updateBookModalSummary(cfg, listing) {
        const startsInput = document.getElementById("fp-book-starts");
        const endsInput = document.getElementById("fp-book-ends");
        const windowEl = document.getElementById("fp-book-window");
        const rateEl = document.getElementById("fp-book-rate");
        const durationEl = document.getElementById("fp-book-duration");
        const totalLine = document.getElementById("fp-book-total-line");
        const submitBtn = document.getElementById("fp-book-submit");
        if (!startsInput || !endsInput || !windowEl || !rateEl || !durationEl || !totalLine) return;

        const starts = parseDatetimeLocal(startsInput.value);
        const ends = parseDatetimeLocal(endsInput.value);
        rateEl.textContent = `${listing.rateDisplay} ${cfg.currencyName}/h`;

        if (!starts || !ends) {
            windowEl.textContent = "Choose when you arrive and leave.";
            durationEl.textContent = "—";
            totalLine.textContent = "—";
            if (submitBtn) submitBtn.disabled = true;
            return;
        }

        if (ends <= starts) {
            windowEl.textContent = "Leave time must be after your arrival.";
            durationEl.textContent = "—";
            totalLine.textContent = "—";
            if (submitBtn) submitBtn.disabled = true;
            return;
        }

        const quote = calcBookingQuote(listing, starts, ends);
        windowEl.textContent = `Parking from ${formatWhen(starts)} to ${formatWhen(ends)}`;
        durationEl.textContent = `${quote.hours} hour${quote.hours === 1 ? "" : "s"}`;
        totalLine.textContent = `${quote.total} ${cfg.currencyName}`;
        if (submitBtn) submitBtn.disabled = !quote.valid;
    }

    function openBookModal(cfg, listingId, mode) {
        mode = mode || "book";
        const listing = (cfg.listings || []).find((l) => l.listingId === listingId);
        const modal = document.getElementById("fp-book-modal");
        const title = document.getElementById("fp-book-title");
        const subtitle = document.getElementById("fp-book-subtitle");
        const meta = document.getElementById("fp-book-meta");
        const listingInput = document.getElementById("fp-book-listing-id");
        const startsInput = document.getElementById("fp-book-starts");
        const endsInput = document.getElementById("fp-book-ends");
        const promoInput = document.getElementById("fp-book-promo");
        const actionInput = document.querySelector("#fp-book-form input[name='action']");
        const watchOptions = document.getElementById("fp-watch-options");
        const promoBlock = promoInput?.closest(".mb-3");
        const summaryBlock = document.querySelector(".fp-book-summary");
        const submitBtn = document.getElementById("fp-book-submit");
        if (!modal || !listing || !startsInput || !endsInput) return;

        listingInput.value = listingId;
        title.textContent = mode === "watch" ? "Watch this spot" : listing.title;
        subtitle.textContent = listing.subtitle;
        meta.textContent =
            mode === "watch"
                ? `${listing.distanceKm} km away · ${listing.predictionLabel || "Not available now"}`
                : `${listing.distanceKm} km away · ${listing.rateDisplay} ${cfg.currencyName}/h`;

        const { start, end } = defaultBookingRange();
        if (cfg.targetAt) {
            const t = parseDatetimeLocal(cfg.targetAt);
            if (t) {
                start.setTime(t.getTime());
                end.setTime(t.getTime() + 2 * 3600000);
            }
        }
        startsInput.value = toDatetimeLocalValue(start);
        endsInput.value = toDatetimeLocalValue(end);
        if (promoInput) promoInput.value = "";

        if (actionInput) actionInput.value = mode === "watch" ? "waitlist" : "schedule_book";
        if (watchOptions) watchOptions.hidden = mode !== "watch";
        if (promoBlock) promoBlock.hidden = mode === "watch";
        if (summaryBlock) summaryBlock.hidden = mode === "watch";
        if (submitBtn) submitBtn.textContent = mode === "watch" ? "Add to watchlist" : "Pay & park";

        const refresh = () => updateBookModalSummary(cfg, listing);
        startsInput.removeEventListener("input", startsInput._fpRefresh);
        endsInput.removeEventListener("input", endsInput._fpRefresh);
        startsInput.removeEventListener("change", startsInput._fpRefresh);
        endsInput.removeEventListener("change", endsInput._fpRefresh);
        startsInput._fpRefresh = refresh;
        endsInput._fpRefresh = refresh;
        startsInput.addEventListener("input", refresh);
        endsInput.addEventListener("input", refresh);
        startsInput.addEventListener("change", refresh);
        endsInput.addEventListener("change", refresh);
        refresh();

        const form = document.getElementById("fp-book-form");
        if (form) {
            form.action = window.location.pathname + window.location.search;
        }

        modal.hidden = false;
        modal.setAttribute("aria-hidden", "false");
        startsInput.focus();
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

        const paidTotal =
            typeof data.total === "number"
                ? formatCreditsFromHundredths(data.total)
                : String(data.total);
        const rows = [
            ["Spot", data.spot],
            ["Paid", `${paidTotal} ${cfg.currencyName}`],
        ];
        if (data.starts && data.ends) rows.push(["When", `${data.starts} – ${data.ends}`]);
        else if (data.hours) rows.push(["Duration", `${data.hours} hour(s)`]);

        details.innerHTML = rows
            .map(([k, v]) => `<li><span class="text-secondary">${escapeHtml(k)}</span> <strong>${escapeHtml(v)}</strong></li>`)
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
                btn.innerHTML = `<span class="fp-suggestion-pin" aria-hidden="true"></span><span>${escapeHtml(row.label)}</span>`;
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

        document.addEventListener("click", (e) => {
            const bookBtn = e.target.closest(".fp-book-open");
            if (bookBtn) {
                const id = parseInt(bookBtn.dataset.listingId, 10);
                if (id) openBookModal(cfg, id, "book");
                return;
            }
            const watchBtn = e.target.closest(".fp-watch-open");
            if (watchBtn) {
                const id = parseInt(watchBtn.dataset.listingId, 10);
                if (id) openBookModal(cfg, id, "watch");
            }
        });

        document.querySelectorAll("[data-fp-scroll]").forEach((btn) => {
            btn.addEventListener("click", () => {
                const id = btn.getAttribute("data-fp-scroll");
                document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
            });
        });
    }

    function wireFilterToggle() {
        const toggle = document.getElementById("fp-filter-toggle");
        const panel = document.getElementById("fp-filters-panel");
        if (!toggle || !panel) return;

        toggle.addEventListener("click", () => {
            const open = panel.hidden;
            panel.hidden = !open;
            toggle.setAttribute("aria-expanded", open ? "true" : "false");
            toggle.setAttribute("aria-label", open ? "Hide filters" : "Show filters");
            toggle.classList.toggle("is-active", open);
        });
    }

    function init(cfg) {
        cfg = cfg || {};
        wireSearch(cfg);
        wireModals(cfg);
        wireFilterToggle();
        if (cfg.searchCenter) {
            const ft = document.getElementById("fp-filter-toggle");
            if (ft) ft.disabled = false;
        }
        initMap(cfg);
        showConfirmation(cfg);
    }

    window.SpotflowFindParking = { init, openBookModal };
})();
