(function () {
    const debounce = (fn, ms) => {
        let t;
        return (...args) => {
            clearTimeout(t);
            t = setTimeout(() => fn(...args), ms);
        };
    };

    function initMap(cfg) {
        const markers = cfg.markers || [];
        const center = cfg.center || { lat: 44.4268, lng: 26.1025 };
        if (!window.SpotflowMaps || !markers.length) {
            const el = document.getElementById("rental-map-loading");
            if (el) el.textContent = markers.length ? "Map unavailable" : "No spots on map";
            return;
        }
        const mapMarkers = markers.map((m) => ({
            lat: m.lat,
            lng: m.lng,
            title: m.title,
            subtitle: m.subtitle,
            status: m.status || "empty",
            actionHtml: m.listingId
                ? `<a href="#listing-${m.listingId}" class="small">View listing</a>`
                : "",
        }));
        SpotflowMaps.render("rental-map", mapMarkers, {
            fitBounds: true,
            center: [center.lat, center.lng],
            zoom: 13,
        })
            .then(() => document.getElementById("rental-map-loading")?.remove())
            .catch(() => {
                const el = document.getElementById("rental-map-loading");
                if (el) el.textContent = "Map unavailable";
            });
    }

    function wireSearch() {
        const input = document.getElementById("fp-search-input");
        const lat = document.getElementById("fp-lat");
        const lng = document.getElementById("fp-lng");
        const box = document.getElementById("fp-suggestions");
        if (!input || !box) return;

        const fetchSuggestions = debounce(async () => {
            const q = input.value.trim();
            if (q.length < 2) {
                box.classList.add("d-none");
                box.innerHTML = "";
                return;
            }
            try {
                const res = await fetch(`/portal/api/geocode?q=${encodeURIComponent(q)}`);
                const data = await res.json();
                box.innerHTML = "";
                (data.results || []).forEach((row) => {
                    const btn = document.createElement("button");
                    btn.type = "button";
                    btn.className = "list-group-item list-group-item-action small";
                    btn.textContent = row.label;
                    btn.addEventListener("click", () => {
                        input.value = row.label;
                        if (lat) lat.value = row.lat;
                        if (lng) lng.value = row.lng;
                        box.classList.add("d-none");
                    });
                    box.appendChild(btn);
                });
                box.classList.toggle("d-none", !box.children.length);
            } catch (_e) {
                box.classList.add("d-none");
            }
        }, 320);

        input.addEventListener("input", fetchSuggestions);
        document.addEventListener("click", (e) => {
            if (!box.contains(e.target) && e.target !== input) box.classList.add("d-none");
        });
    }

    function init(cfg) {
        wireSearch();
        if (cfg) initMap(cfg);
    }

    window.SpotflowFindParking = { init };
})();
