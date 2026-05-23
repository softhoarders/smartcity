(function () {
    const STATUS_COLORS = {
        violation: "#FF453A",
        occupied: "#FF9F0A",
        empty: "#30D158",
        correct: "#0A84FF",
        illegal: "#FF453A",
        unknown: "#8E8E93",
    };

    const LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
    const LEAFLET_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    const TILE_URL = "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png";
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
            const L = await loadLeaflet();
            container.classList.add("pw-map-host", "pw-map-surface");

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
                subdomains: "abcd",
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
