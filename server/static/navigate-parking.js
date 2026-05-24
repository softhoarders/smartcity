(function () {
    const OSRM_BASE = "https://router.project-osrm.org/route/v1/driving";
    const STEP_ICONS = {
        depart: "▶",
        arrive: "◎",
        turn: "↱",
        "new name": "↑",
        continue: "↑",
        roundabout: "⟳",
        merge: "↗",
        on_ramp: "↗",
        off_ramp: "↘",
        fork: "⑂",
        end_of_road: "↱",
        default: "•",
    };

    const LOT_ICONS = {
        enter: "🚧",
        straight: "↑",
        turn: "↱",
        spot: "P",
    };

    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function formatDistance(m) {
        if (m == null || Number.isNaN(m)) return "";
        if (m < 1000) return `${Math.round(m)} m`;
        return `${(m / 1000).toFixed(1)} km`;
    }

    function formatDuration(sec) {
        if (sec == null || Number.isNaN(sec)) return "";
        const min = Math.max(1, Math.round(sec / 60));
        if (min < 60) return `${min} min`;
        const h = Math.floor(min / 60);
        const r = min % 60;
        return r ? `${h} h ${r} min` : `${h} h`;
    }

    function haversineM(lat1, lng1, lat2, lng2) {
        const R = 6371000;
        const toRad = (d) => (d * Math.PI) / 180;
        const dLat = toRad(lat2 - lat1);
        const dLng = toRad(lng2 - lng1);
        const a =
            Math.sin(dLat / 2) ** 2 +
            Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
        return 2 * R * Math.asin(Math.sqrt(a));
    }

    async function fetchOsrmRoute(from, to) {
        const coords = `${from.lng},${from.lat};${to.lng},${to.lat}`;
        const url = `${OSRM_BASE}/${coords}?overview=full&geometries=geojson&steps=true&annotations=false`;
        const res = await fetch(url, { headers: { Accept: "application/json" } });
        if (!res.ok) throw new Error("Routing service unavailable");
        const data = await res.json();
        if (data.code !== "Ok" || !data.routes?.length) {
            throw new Error(data.message || "No driving route found");
        }
        return data.routes[0];
    }

    function flattenOsrmSteps(route) {
        const out = [];
        for (const leg of route.legs || []) {
            for (const step of leg.steps || []) {
                const maneuver = step.maneuver || {};
                const type = maneuver.type || "continue";
                const mod = maneuver.modifier ? ` ${maneuver.modifier}` : "";
                const name = step.name ? ` onto ${step.name}` : "";
                let instruction = step.maneuver?.instruction;
                if (!instruction) {
                    if (type === "depart") instruction = `Head ${maneuver.modifier || "straight"}${name}`;
                    else if (type === "arrive") instruction = "Arrive at parking lot entrance";
                    else instruction = `${type.replace(/_/g, " ")}${mod}${name}`;
                }
                out.push({
                    phase: "road",
                    kind: type,
                    instruction,
                    distance_m: step.distance,
                    duration_s: step.duration,
                });
            }
        }
        return out;
    }

    function renderRoadSteps(container, steps) {
        if (!steps.length) {
            container.innerHTML =
                '<li class="nav-parking-step nav-parking-step--muted"><span>Enable location or move closer to see driving directions.</span></li>';
            return;
        }
        container.innerHTML = steps
            .map((step, idx) => {
                const icon = STEP_ICONS[step.kind] || STEP_ICONS.default;
                const meta = [formatDistance(step.distance_m), formatDuration(step.duration_s)]
                    .filter(Boolean)
                    .join(" · ");
                const active = idx === 0 ? " nav-parking-step--active" : "";
                return `<li class="nav-parking-step${active}" data-step-index="${idx}">
                    <span class="nav-parking-step-icon" aria-hidden="true">${icon}</span>
                    <span>
                        <span class="nav-parking-step-text">${escapeHtml(step.instruction)}</span>
                        ${meta ? `<span class="nav-parking-step-meta">${escapeHtml(meta)}</span>` : ""}
                    </span>
                </li>`;
            })
            .join("");
    }

    function getUserLocation() {
        return new Promise((resolve, reject) => {
            if (!navigator.geolocation) {
                reject(new Error("Geolocation not supported"));
                return;
            }
            navigator.geolocation.getCurrentPosition(
                (pos) =>
                    resolve({
                        lat: pos.coords.latitude,
                        lng: pos.coords.longitude,
                        accuracy: pos.coords.accuracy,
                    }),
                (err) => reject(err),
                { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 }
            );
        });
    }

    async function init(cfg) {
        const spot = cfg.spot;
        const entrance = cfg.entrance;
        if (!spot?.lat || !spot?.lng) return;

        const mapEl = document.getElementById("nav-parking-map");
        const loadingEl = document.getElementById("nav-parking-map-loading");
        const roadStepsEl = document.getElementById("nav-road-steps");
        const summaryEl = document.getElementById("nav-route-summary");
        const recenterBtn = document.getElementById("nav-recenter-btn");
        const useLocBtn = document.getElementById("nav-use-location");

        let userMarker = null;
        let routeLayer = null;
        let mapApi = null;
        let lastUser = null;

        const markers = [
            {
                lat: entrance.lat,
                lng: entrance.lng,
                title: "Lot entrance",
                subtitle: "End of street navigation",
                status: "correct",
                statusLabel: "Entrance",
                kind: "destination",
                color: "#64D2FF",
            },
            {
                lat: spot.lat,
                lng: spot.lng,
                title: spot.label,
                subtitle: spot.location_name || "Your reserved bay",
                status: "empty",
                statusLabel: "Your spot",
                color: "#30D158",
            },
        ];

        if (loadingEl) loadingEl.remove();

        mapApi = await window.SpotflowMaps.render("nav-parking-map", markers, {
            fitBounds: true,
            maxZoom: 17,
            padding: [48, 48],
            onReady: ({ map }) => {
                if (routeLayer) routeLayer.addTo(map);
            },
        });

        const drawRoute = (route) => {
            if (!mapApi?.map || !route?.geometry?.coordinates) return;
            if (routeLayer) {
                routeLayer.remove();
            }
            const latlngs = route.geometry.coordinates.map(([lng, lat]) => [lat, lng]);
            routeLayer = L.polyline(latlngs, {
                color: "#0A84FF",
                weight: 5,
                opacity: 0.85,
                lineCap: "round",
            }).addTo(mapApi.map);

            const bounds = routeLayer.getBounds();
            if (lastUser) {
                bounds.extend([lastUser.lat, lastUser.lng]);
            }
            bounds.extend([spot.lat, spot.lng]);
            bounds.extend([entrance.lat, entrance.lng]);
            mapApi.map.fitBounds(bounds, { padding: [56, 56], maxZoom: 16 });
        };

        const setUserMarker = (loc) => {
            if (!mapApi?.map) return;
            lastUser = loc;
            const html = `<div class="pw-map-pin pw-map-pin--user" style="--pin-color:#FFD60A"><span class="pw-map-pin-user"></span></div>`;
            const icon = L.divIcon({
                className: "pw-map-marker-wrap",
                html,
                iconSize: [28, 28],
                iconAnchor: [14, 14],
            });
            if (userMarker) userMarker.remove();
            userMarker = L.marker([loc.lat, loc.lng], { icon, zIndexOffset: 2000 }).addTo(mapApi.map);
            userMarker.bindPopup("You are here", { className: "pw-map-popup" });
        };

        const loadRoute = async (from) => {
            try {
                const route = await fetchOsrmRoute(from, entrance);
                const steps = flattenOsrmSteps(route);
                renderRoadSteps(roadStepsEl, steps);
                drawRoute(route);
                const dist = formatDistance(route.distance);
                const dur = formatDuration(route.duration);
                if (summaryEl) summaryEl.textContent = `${dist} · ${dur} to lot entrance`;
            } catch (err) {
                console.warn("[NavigateParking]", err);
                const fallbackDist = haversineM(from.lat, from.lng, entrance.lat, entrance.lng);
                renderRoadSteps(roadStepsEl, [
                    {
                        phase: "road",
                        kind: "continue",
                        instruction: `Head toward the parking lot entrance (${formatDistance(fallbackDist)} as the crow flies).`,
                        distance_m: fallbackDist,
                    },
                    {
                        phase: "road",
                        kind: "arrive",
                        instruction: "Arrive at the lot entrance, then follow the in-lot steps below.",
                    },
                ]);
                if (summaryEl) summaryEl.textContent = `~${formatDistance(fallbackDist)} to entrance · offline estimate`;
                if (mapApi?.map) {
                    mapApi.map.fitBounds(
                        [
                            [from.lat, from.lng],
                            [entrance.lat, entrance.lng],
                            [spot.lat, spot.lng],
                        ],
                        { padding: [56, 56], maxZoom: 15 }
                    );
                }
            }
        };

        const startFromUser = async () => {
            if (summaryEl) summaryEl.textContent = "Getting your location…";
            try {
                const loc = await getUserLocation();
                setUserMarker(loc);
                await loadRoute(loc);
            } catch {
                const center = cfg.searchCenter;
                if (center?.lat && center?.lng) {
                    const loc = { lat: Number(center.lat), lng: Number(center.lng) };
                    renderRoadSteps(roadStepsEl, [
                        {
                            phase: "road",
                            kind: "depart",
                            instruction: `Start from ${center.label || "your search area"} and drive to the lot entrance.`,
                        },
                        {
                            phase: "road",
                            kind: "arrive",
                            instruction: "Allow location access for live turn-by-turn driving directions.",
                        },
                    ]);
                    if (summaryEl) summaryEl.textContent = "Tap “Use my location” for live directions";
                    if (mapApi?.map) {
                        mapApi.map.fitBounds(
                            [
                                [loc.lat, loc.lng],
                                [entrance.lat, entrance.lng],
                                [spot.lat, spot.lng],
                            ],
                            { padding: [56, 56], maxZoom: 14 }
                        );
                    }
                } else {
                    renderRoadSteps(roadStepsEl, [
                        {
                            phase: "road",
                            kind: "arrive",
                            instruction:
                                "Allow location access to get driving directions to the parking lot entrance.",
                        },
                    ]);
                    if (summaryEl) summaryEl.textContent = "Location needed for driving directions";
                }
            }
        };

        recenterBtn?.addEventListener("click", () => {
            if (!mapApi?.map) return;
            const pts = [[entrance.lat, entrance.lng], [spot.lat, spot.lng]];
            if (lastUser) pts.push([lastUser.lat, lastUser.lng]);
            mapApi.map.fitBounds(pts, { padding: [56, 56], maxZoom: 16 });
        });

        useLocBtn?.addEventListener("click", startFromUser);

        await startFromUser();
    }

    window.SpotflowNavigateParking = { init };
})();
