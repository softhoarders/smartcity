(function () {
    const STATUS_COLORS = {
        violation: "#FF3B30",
        occupied: "#FF9500",
        empty: "#34C759",
        correct: "#007AFF",
        illegal: "#FF3B30",
        unknown: "#8E8E93",
    };

    const LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
    const LEAFLET_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    const TILE_URL = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png";
    const TILE_ATTR =
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>';

    let leafletReady = null;

    function loadLeaflet() {
        if (window.L) {
            return Promise.resolve(window.L);
        }
        if (leafletReady) {
            return leafletReady;
        }

        leafletReady = new Promise((resolve, reject) => {
            if (!document.querySelector("link[data-parkscan-leaflet]")) {
                const link = document.createElement("link");
                link.rel = "stylesheet";
                link.href = LEAFLET_CSS;
                link.dataset.parkscanLeaflet = "1";
                document.head.appendChild(link);
            }

            const script = document.createElement("script");
            script.src = LEAFLET_JS;
            script.async = true;
            script.onload = () => resolve(window.L);
            script.onerror = () => reject(new Error("Leaflet failed to load"));
            document.head.appendChild(script);
        });

        return leafletReady;
    }

    function popupHtml(marker) {
        const color = marker.color || STATUS_COLORS[marker.status] || STATUS_COLORS.unknown;
        const statusLine = marker.status
            ? `<br><span style="color:${color};font-weight:600;text-transform:capitalize">${marker.status}</span>`
            : "";
        return `<strong>${marker.title || ""}</strong><br>${marker.subtitle || ""}${statusLine}`;
    }

    async function render(containerId, markers, options) {
        const container = document.getElementById(containerId);
        if (!container) {
            return null;
        }

        try {
            const L = await loadLeaflet();
            container.classList.add("pw-map-host");

            if (container._parkscanMap) {
                container._parkscanMap.remove();
                container._parkscanMap = null;
            }

            const map = L.map(container, {
                zoomControl: true,
                attributionControl: true,
            });

            L.tileLayer(TILE_URL, {
                attribution: TILE_ATTR,
                maxZoom: 20,
            }).addTo(map);

            container._parkscanMap = map;

            const safeMarkers = (markers || []).filter((m) => m.lat != null && m.lng != null);
            const bounds = [];

            safeMarkers.forEach((marker) => {
                const lat = marker.lat;
                const lng = marker.lng;
                bounds.push([lat, lng]);
                const color = marker.color || STATUS_COLORS[marker.status] || STATUS_COLORS.unknown;
                const icon = L.divIcon({
                    className: "pw-map-marker-wrap",
                    html: `<div class="pw-map-marker" style="--marker-color:${color}"></div>`,
                    iconSize: [20, 20],
                    iconAnchor: [10, 10],
                });
                L.marker([lat, lng], { icon }).addTo(map).bindPopup(popupHtml(marker));
            });

            if (bounds.length === 1) {
                map.setView(bounds[0], options?.zoom || 16);
            } else if (bounds.length > 1) {
                map.fitBounds(bounds, { padding: [40, 40] });
            } else {
                map.setView([44.4268, 26.1025], 12);
            }

            setTimeout(() => map.invalidateSize(), 120);
            return map;
        } catch (error) {
            console.error("[ParkScanMaps]", error);
            container.innerHTML =
                '<div class="pw-map-fallback">Map could not be loaded. Check your network connection.</div>';
            return null;
        }
    }

    window.ParkScanMaps = {
        STATUS_COLORS,
        render,
    };
})();
