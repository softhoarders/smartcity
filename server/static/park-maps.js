(function () {
    const STATUS_COLORS = {
        violation: "#FF453A",
        occupied: "#FF9F0A",
        empty: "#30D158",
        correct: "#0A84FF",
        illegal: "#FF453A",
        unknown: "#8E8E93",
    };

    const TILE_URL =
        "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png";
    const TILE_ATTR =
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> ' +
        '&copy; <a href="https://carto.com/attributions">CARTO</a>';

    function ensureLeaflet() {
        if (window.L) {
            return Promise.resolve(window.L);
        }
        return Promise.reject(
            new Error("Leaflet is not loaded. Include park_map_assets() before park-maps.js.")
        );
    }

    function popupHtml(marker) {
        const color = marker.color || STATUS_COLORS[marker.status] || STATUS_COLORS.unknown;
        const statusLine = marker.status
            ? `<div class="pw-map-popup-status" style="color:${color}">${marker.status}</div>`
            : "";
        return `<div class="pw-map-popup-title">${marker.title || ""}</div>
                <div class="pw-map-popup-sub">${marker.subtitle || ""}</div>
                ${statusLine}`;
    }

    async function render(containerId, markers, options) {
        const container = document.getElementById(containerId);
        if (!container) {
            return null;
        }

        try {
            const L = await ensureLeaflet();
            container.classList.add("pw-map-host", "pw-map-surface", "pw-map-glass");
            container.innerHTML = "";

            if (container._spotflowMap) {
                container._spotflowMap.remove();
                container._spotflowMap = null;
            }
            if (container._spotflowMapOverlay) {
                container._spotflowMapOverlay.remove();
                container._spotflowMapOverlay = null;
            }

            const map = L.map(container, {
                zoomControl: false,
                attributionControl: true,
                fadeAnimation: true,
                zoomAnimation: true,
            });

            L.tileLayer(TILE_URL, {
                attribution: TILE_ATTR,
                subdomains: "abcd",
                maxZoom: 20,
            }).addTo(map);

            L.control
                .zoom({ position: "bottomright" })
                .addTo(map);

            const overlay = document.createElement("div");
            overlay.className = "pw-map-glass-overlay";
            overlay.setAttribute("aria-hidden", "true");
            container.appendChild(overlay);
            container._spotflowMapOverlay = overlay;

            container._spotflowMap = map;

            const safeMarkers = (markers || []).filter((m) => m.lat != null && m.lng != null);
            const bounds = [];

            safeMarkers.forEach((marker) => {
                const lat = marker.lat;
                const lng = marker.lng;
                bounds.push([lat, lng]);
                const color = marker.color || STATUS_COLORS[marker.status] || STATUS_COLORS.unknown;
                const icon = L.divIcon({
                    className: "pw-map-marker-wrap",
                    html: `<div class="pw-map-pin" style="--pin-color:${color}"><span class="pw-map-pin-core"></span></div>`,
                    iconSize: [28, 28],
                    iconAnchor: [14, 14],
                });
                L.marker([lat, lng], { icon }).addTo(map).bindPopup(popupHtml(marker), {
                    className: "pw-map-popup",
                    maxWidth: 260,
                });
            });

            if (bounds.length === 1) {
                map.setView(bounds[0], options?.zoom || 16);
            } else if (bounds.length > 1) {
                map.fitBounds(bounds, { padding: [48, 48] });
            } else {
                map.setView([44.4268, 26.1025], 12);
            }

            const refresh = () => map.invalidateSize();
            setTimeout(refresh, 0);
            setTimeout(refresh, 150);
            setTimeout(refresh, 400);
            if (typeof ResizeObserver !== "undefined") {
                const ro = new ResizeObserver(refresh);
                ro.observe(container);
                container._spotflowMapResize = ro;
            }
            return map;
        } catch (error) {
            console.error("[SpotflowMaps]", error);
            container.innerHTML =
                '<div class="pw-map-fallback">Map could not be loaded. Check your network connection.</div>';
            return null;
        }
    }

    window.SpotflowMaps = {
        STATUS_COLORS,
        render,
    };
})();
