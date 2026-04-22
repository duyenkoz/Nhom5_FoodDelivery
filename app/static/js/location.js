(function () {
    const AUTOCOMPLETE_SELECTOR = "[data-location-autocomplete]";
    const SEARCH_DEBOUNCE_MS = 300;

    function toStorageKey(rawKey) {
        return rawKey && rawKey.trim() ? rawKey.trim() : "fivefood:location:anonymous";
    }

    function readStoredLocation(storageKey) {
        try {
            const raw = localStorage.getItem(storageKey);
            if (!raw) {
                return null;
            }

            const parsed = JSON.parse(raw);
            if (
                !parsed ||
                !(parsed.address || parsed.display_name || parsed.formatted_address) ||
                parsed.lat === undefined ||
                parsed.lon === undefined
            ) {
                return null;
            }

            return parsed;
        } catch (error) {
            return null;
        }
    }

    function storeLocation(storageKey, location) {
        try {
            localStorage.setItem(storageKey, JSON.stringify(location));
        } catch (error) {
            // Ignore storage quota and privacy restrictions.
        }
    }

    function buildLocationUrl(location) {
        const url = new URL(window.location.href);
        url.searchParams.set(
            "address",
            location.display_name || location.address || location.formatted_address || location.description || location.name || ""
        );
        url.searchParams.set("lat", location.lat);
        url.searchParams.set("lon", location.lon);
        if (location.area) {
            url.searchParams.set("area", location.area);
        } else {
            url.searchParams.delete("area");
        }
        return url;
    }

    function getItemLabel(location) {
        return (
            (location.structured_formatting && location.structured_formatting.main_text) ||
            location.name ||
            location.display_name ||
            location.address ||
            location.description ||
            ""
        );
    }

    function getItemMeta(location) {
        if (location.structured_formatting && location.structured_formatting.secondary_text) {
            return location.structured_formatting.secondary_text;
        }

        return [location.area, location.type].filter(Boolean).join(" - ");
    }

    function createItemButton(location) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "location-autocomplete__item";
        button.setAttribute("role", "option");
        button.setAttribute("aria-selected", "false");
        button.dataset.locationItem = "true";
        button.dataset.locationPayload = JSON.stringify(location);

        const label = document.createElement("strong");
        label.className = "location-autocomplete__label";
        label.textContent = getItemLabel(location);
        button.appendChild(label);

        const metaText = getItemMeta(location);
        if (metaText) {
            const meta = document.createElement("span");
            meta.className = "location-autocomplete__meta";
            meta.textContent = metaText;
            button.appendChild(meta);
        }

        return button;
    }

    function initWidget(container) {
        const input = container.querySelector("[data-location-input]");
        const dropdown = container.querySelector("[data-location-dropdown]");
        if (!input || !dropdown) {
            return;
        }

        const searchUrl = container.dataset.locationSearchUrl;
        const resolveUrl = container.dataset.locationResolveUrl;
        const storageKey = toStorageKey(container.dataset.locationStorageKey);
        const mode = container.dataset.locationMode || "form";
        const areaSelector = container.dataset.locationAreaSelector || "";
        const areaInput = areaSelector ? document.querySelector(areaSelector) : null;
        const clearOnSelect = container.dataset.locationClearOnSelect !== "false";
        const shouldPersist = container.dataset.locationPersist === "true";
        const requireArea = container.dataset.locationRequireArea === "true";
        const disableUntilArea = container.dataset.locationDisableUntilArea === "true";
        const clearStorageKey = container.dataset.locationClearStorageKey || "";
        let activeIndex = -1;
        let currentResults = [];
        let debounceHandle = null;
        let abortController = null;
        let requestSequence = 0;

        function getSelectedArea() {
            return areaInput && typeof areaInput.value === "string" ? areaInput.value.trim() : "";
        }

        function syncAreaState() {
            if (!disableUntilArea) {
                return;
            }

            const hasArea = Boolean(getSelectedArea());
            input.disabled = !hasArea;
            input.classList.toggle("is-disabled", !hasArea);

            if (!hasArea) {
                clearResults();
                if (input.value.trim()) {
                    input.value = "";
                }
            }
        }

        function setLoading(isLoading) {
            if (isLoading) {
                container.classList.add("is-loading");
                dropdown.innerHTML = '<div class="location-autocomplete__empty location-autocomplete__empty--loading">Đang tìm địa chỉ...</div>';
                setOpen(true);
            } else {
                container.classList.remove("is-loading");
            }
        }

        function setOpen(isOpen) {
            dropdown.hidden = !isOpen;
            container.classList.toggle("is-open", isOpen);
        }

        function clearResults() {
            currentResults = [];
            activeIndex = -1;
            dropdown.innerHTML = "";
            container.classList.remove("is-loading");
            setOpen(false);
        }

        function syncActiveItem() {
            Array.from(dropdown.querySelectorAll("[data-location-item='true']")).forEach((item) => {
                const index = Number(item.dataset.index);
                const isActive = index === activeIndex;
                item.classList.toggle("is-active", isActive);
                item.setAttribute("aria-selected", isActive ? "true" : "false");
            });
        }

        function applyLocation(location) {
            input.value =
                location.display_name ||
                location.address ||
                location.formatted_address ||
                location.description ||
                location.name ||
                "";

            if (shouldPersist) {
                storeLocation(storageKey, location);
            }

            if (mode === "home") {
                window.location.replace(buildLocationUrl(location).toString());
                return;
            }

            if (clearOnSelect) {
                clearResults();
            }
        }

        function renderResults(results) {
            container.classList.remove("is-loading");
            currentResults = results.slice(0, 8);
            dropdown.innerHTML = "";

            if (!currentResults.length) {
                const empty = document.createElement("div");
                empty.className = "location-autocomplete__empty";
                empty.textContent = "Không tìm thấy địa chỉ. Thử thêm quận hoặc thành phố.";
                dropdown.appendChild(empty);
                setOpen(true);
                return;
            }

            currentResults.forEach((location, index) => {
                const item = createItemButton(location);
                item.dataset.index = String(index);
                item.addEventListener("click", () => {
                    applyLocation(location);
                });
                dropdown.appendChild(item);
            });

            activeIndex = -1;
            syncActiveItem();
            setOpen(true);
        }

        function fetchBackendResults(query) {
            if (!searchUrl) {
                return Promise.resolve([]);
            }

            if (requireArea && !getSelectedArea()) {
                return Promise.resolve([]);
            }

            const url = new URL(searchUrl, window.location.origin);
            url.searchParams.set("q", query);

            const selectedArea = getSelectedArea();
            if (selectedArea) {
                url.searchParams.set("area", selectedArea);
            }

            return fetch(url.toString(), {
                headers: { Accept: "application/json" },
                signal: abortController ? abortController.signal : undefined,
            })
                .then((response) => {
                    if (!response.ok) {
                        return [];
                    }
                    return response.json().then((payload) => (Array.isArray(payload.results) ? payload.results : []));
                })
                .catch(() => []);
        }

        function fetchResults(query) {
            if (!query || query.trim().length < 2) {
                clearResults();
                return;
            }

            if (requireArea && !getSelectedArea()) {
                clearResults();
                return;
            }

            if (abortController) {
                abortController.abort();
            }

            abortController = new AbortController();
            const requestId = ++requestSequence;
            setLoading(true);

            fetchBackendResults(query)
                .then((results) => {
                    if (requestId !== requestSequence || abortController.signal.aborted) {
                        return [];
                    }

                    if (results.length) {
                        renderResults(results);
                    } else {
                        clearResults();
                    }

                    return results;
                })
                .catch((error) => {
                    if (error.name !== "AbortError") {
                        clearResults();
                    }
                })
                .finally(() => {
                    container.classList.remove("is-loading");
                });
        }

        function resolveFreeText() {
            if (!resolveUrl) {
                return;
            }

            const query = input.value.trim();
            if (!query) {
                clearResults();
                return;
            }

            if (requireArea && !getSelectedArea()) {
                clearResults();
                return;
            }

            const url = new URL(resolveUrl, window.location.origin);
            url.searchParams.set("q", query);

            const selectedArea = getSelectedArea();
            if (selectedArea) {
                url.searchParams.set("area", selectedArea);
            }

            fetch(url.toString(), {
                headers: { Accept: "application/json" },
            })
                .then((response) => response.json().then((payload) => ({ status: response.status, payload })))
                .then(({ status, payload }) => {
                    if (status >= 400 || !payload || !payload.ok || !payload.location) {
                        clearResults();
                        return;
                    }

                    applyLocation(payload.location);
                })
                .catch(() => {
                    clearResults();
                });
        }

        function handleKeydown(event) {
            if (dropdown.hidden) {
                if (mode === "home" && event.key === "Enter") {
                    event.preventDefault();
                    resolveFreeText();
                }
                return;
            }

            if (event.key === "ArrowDown") {
                event.preventDefault();
                activeIndex = Math.min(activeIndex + 1, currentResults.length - 1);
                syncActiveItem();
            } else if (event.key === "ArrowUp") {
                event.preventDefault();
                activeIndex = Math.max(activeIndex - 1, 0);
                syncActiveItem();
            } else if (event.key === "Enter") {
                event.preventDefault();
                if (currentResults[activeIndex]) {
                    applyLocation(currentResults[activeIndex]);
                } else if (currentResults.length) {
                    applyLocation(currentResults[0]);
                } else if (mode === "home") {
                    resolveFreeText();
                }
            } else if (event.key === "Escape") {
                clearResults();
            }
        }

        function refreshStoredLocation() {
            if (clearStorageKey) {
                try {
                    localStorage.removeItem(clearStorageKey);
                } catch (error) {
                    // Ignore storage restrictions.
                }
            }

            if (!shouldPersist) {
                return;
            }

            const stored = readStoredLocation(storageKey);
            const currentUrl = new URL(window.location.href);
            const hasUrlLocation = currentUrl.searchParams.has("lat") && currentUrl.searchParams.has("lon");

            if (stored && mode === "home" && !hasUrlLocation) {
                window.location.replace(buildLocationUrl(stored).toString());
                return;
            }

            if (stored && input.value.trim() === "") {
                input.value = stored.address || stored.display_name || stored.formatted_address || "";
            }
        }

        input.addEventListener("input", () => {
            if (requireArea && !getSelectedArea()) {
                clearResults();
                return;
            }

            window.clearTimeout(debounceHandle);
            const value = input.value.trim();
            if (!value) {
                clearResults();
                return;
            }

            debounceHandle = window.setTimeout(() => fetchResults(value), SEARCH_DEBOUNCE_MS);
        });

        input.addEventListener("focus", () => {
            if (dropdown.children.length) {
                setOpen(true);
            }
        });

        input.addEventListener("keydown", handleKeydown);
        input.addEventListener("blur", () => {
            window.setTimeout(() => {
                if (!container.matches(":focus-within")) {
                    setOpen(false);
                }
            }, 120);
        });

        if (areaInput) {
            areaInput.addEventListener("change", () => {
                syncAreaState();
                if (input.value.trim() && getSelectedArea()) {
                    fetchResults(input.value.trim());
                }
            });
        }

        syncAreaState();
        refreshStoredLocation();
    }

    function initAll() {
        document.querySelectorAll(AUTOCOMPLETE_SELECTOR).forEach(initWidget);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initAll);
    } else {
        initAll();
    }
})();
