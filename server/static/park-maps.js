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
        const statusLine = marker.statusLabel
            ? `<div class="pw-map-popup-status" style="color:${color}">${marker.statusLabel}</div>`
            : marker.status
              ? `<div class="pw-map-popup-status" style="color:${color}">${marker.status}</div>`
              : "";
        const meta = marker.meta
            ? `<div class="pw-map-popup-meta">${marker.meta}</div>`
            : "";
        const action = marker.actionHtml || "";
        return `<div class="pw-map-popup-title">${marker.title || ""}</div>
                <div class="pw-map-popup-sub">${marker.subtitle || ""}</div>
                ${meta}
                ${statusLine}
                ${action}`;
    }

    function pinHtml(marker, color) {
        const count =
            marker.count > 1
                ? `<span class="pw-map-pin-count" aria-label="${marker.count} alerts">${marker.count}</span>`
                : "";
        return `<div class="pw-map-pin" style="--pin-color:${color}"><span class="pw-map-pin-core"></span>${count}</div>`;
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
            const markerRefs = [];

            safeMarkers.forEach((marker) => {
                const lat = marker.lat;
                const lng = marker.lng;
                bounds.push([lat, lng]);
                const color = marker.color || STATUS_COLORS[marker.status] || STATUS_COLORS.unknown;
                const icon = L.divIcon({
                    className: "pw-map-marker-wrap",
                    html: pinHtml(marker, color),
                    iconSize: [32, 32],
                    iconAnchor: [16, 16],
                });
                const leafletMarker = L.marker([lat, lng], { icon }).addTo(map).bindPopup(popupHtml(marker), {
                    className: "pw-map-popup",
                    maxWidth: 280,
                });
                if (marker.id != null) {
                    leafletMarker._spotflowId = marker.id;
                }
                if (typeof options?.onMarkerClick === "function") {
                    leafletMarker.on("click", function () {
                        options.onMarkerClick(marker, leafletMarker);
                    });
                }
                markerRefs.push({ data: marker, leaflet: leafletMarker });
            });

            const fitPadding = options?.padding || [52, 52];
            const maxZoom = options?.maxZoom ?? 16;
            if (bounds.length === 1) {
                map.setView(bounds[0], options?.zoom || 16);
            } else if (bounds.length > 1 && options?.fitBounds !== false) {
                map.fitBounds(bounds, { padding: fitPadding, maxZoom: maxZoom });
            } else if (!bounds.length) {
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
            if (typeof options?.onReady === "function") {
                options.onReady({ map, markers: markerRefs });
            }
            return { map, markers: markerRefs };
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
