(function () {
    const TONE_COLORS = {
        danger: "#FF453A",
        pending: "#FF9F0A",
        open: "#FFCC00",
        resolved: "#30D158",
    };

    const TONE_RANK = { danger: 4, pending: 3, open: 2, resolved: 1 };

    function worstTone(a, b) {
        return (TONE_RANK[a] || 0) >= (TONE_RANK[b] || 0) ? a : b;
    }

    function groupAlerts(alerts) {
        const groups = new Map();
        alerts.forEach(function (alert) {
            const key = alert.lat + "," + alert.lng;
            if (!groups.has(key)) {
                groups.set(key, {
                    id: key,
                    lat: alert.lat,
                    lng: alert.lng,
                    title: alert.spot,
                    subtitle: alert.place,
                    tone: alert.tone,
                    statusLabel: alert.statusLabel,
                    count: 1,
                    fineIds: [alert.fineId],
                    alerts: [alert],
                });
                return;
            }
            const group = groups.get(key);
            group.count += 1;
            group.fineIds.push(alert.fineId);
            group.alerts.push(alert);
            group.tone = worstTone(group.tone, alert.tone);
            if (group.tone === alert.tone) {
                group.statusLabel = alert.statusLabel;
            } else if (TONE_RANK[alert.tone] > TONE_RANK[group.tone]) {
                group.statusLabel = alert.statusLabel;
            }
        });
        return Array.from(groups.values());
    }

    function toMapMarkers(groups) {
        return groups.map(function (group) {
            const meta =
                group.count > 1
                    ? group.count + " alerts at this spot"
                    : group.alerts[0].when || "";
            return {
                id: group.id,
                lat: group.lat,
                lng: group.lng,
                title: group.title,
                subtitle: group.subtitle,
                color: TONE_COLORS[group.tone] || TONE_COLORS.open,
                statusLabel: group.statusLabel,
                meta: meta,
                count: group.count,
                fineIds: group.fineIds.slice(),
            };
        });
    }

    function scrollToAlert(fineId) {
        const card = document.getElementById("alert-" + fineId);
        if (!card) return;
        card.scrollIntoView({ behavior: "smooth", block: "nearest" });
        card.classList.add("portal-alert--focus");
        window.setTimeout(function () {
            card.classList.remove("portal-alert--focus");
        }, 2200);
    }

    function setActiveSpot(spotId) {
        document.querySelectorAll(".portal-map-spot").forEach(function (btn) {
            btn.classList.toggle("is-active", btn.dataset.spotId === spotId);
        });
    }

    function init(config) {
        const container = document.getElementById(config.mapId);
        const loading = document.getElementById(config.loadingId);
        const spotsRail = document.getElementById(config.spotsId);
        const fitBtn = document.getElementById(config.fitId);
        if (!container || !window.SpotflowMaps) {
            return;
        }

        const alerts = config.alerts || [];
        const groups = groupAlerts(alerts);
        const markers = toMapMarkers(groups);
        const leafletById = new Map();

        function focusSpot(spotId, fineId) {
            setActiveSpot(spotId);
            const entry = leafletById.get(spotId);
            if (entry) {
                entry.leaflet.openPopup();
                entry.map.flyTo([entry.data.lat, entry.data.lng], Math.max(entry.map.getZoom(), 15), {
                    duration: 0.55,
                });
            }
            if (fineId) {
                scrollToAlert(fineId);
            } else {
                const group = groups.find(function (g) {
                    return g.id === spotId;
                });
                if (group && group.fineIds[0]) {
                    scrollToAlert(group.fineIds[0]);
                }
            }
        }

        if (spotsRail) {
            spotsRail.innerHTML = "";
            groups.forEach(function (group) {
                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = "portal-map-spot portal-map-spot--" + group.tone;
                btn.dataset.spotId = group.id;
                btn.setAttribute("aria-label", group.title + ", " + group.count + " alert(s)");
                btn.innerHTML =
                    '<span class="portal-map-spot-dot" aria-hidden="true"></span>' +
                    '<span class="portal-map-spot-text">' +
                    '<span class="portal-map-spot-label">' +
                    group.title +
                    "</span>" +
                    '<span class="portal-map-spot-meta">' +
                    group.subtitle +
                    (group.count > 1 ? " · " + group.count + " alerts" : "") +
                    "</span>" +
                    "</span>" +
                    '<span class="portal-map-spot-badge">' +
                    group.statusLabel +
                    "</span>";
                btn.addEventListener("click", function () {
                    focusSpot(group.id, group.fineIds[0]);
                });
                spotsRail.appendChild(btn);
            });
        }

        SpotflowMaps.render(config.mapId, markers, {
            fitBounds: true,
            padding: [56, 56],
            maxZoom: 15,
            onMarkerClick: function (marker) {
                focusSpot(marker.id, marker.fineIds && marker.fineIds[0]);
            },
            onReady: function (ctx) {
                ctx.markers.forEach(function (entry) {
                    leafletById.set(entry.data.id, { map: ctx.map, data: entry.data, leaflet: entry.leaflet });
                });
                if (loading) {
                    loading.remove();
                }
                if (fitBtn) {
                    fitBtn.disabled = false;
                    fitBtn.addEventListener("click", function () {
                        const bounds = markers.map(function (m) {
                            return [m.lat, m.lng];
                        });
                        if (bounds.length === 1) {
                            ctx.map.setView(bounds[0], 15);
                        } else if (bounds.length > 1) {
                            ctx.map.fitBounds(bounds, { padding: [56, 56], maxZoom: 15 });
                        }
                    });
                }
            },
        }).catch(function (err) {
            console.error("[portal-map]", err);
            if (loading) {
                loading.textContent = "Map unavailable — check your connection";
                loading.classList.add("portal-map-loading--error");
            }
        });
    }

    window.SpotflowPortalMap = { init: init };
})();
