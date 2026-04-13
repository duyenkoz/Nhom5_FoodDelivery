(function () {
    const AUTOCOMPLETE_SELECTOR = "[data-search-autocomplete='true']";
    const RECENT_LIMIT = 5;
    const HOT_LIMIT = 10;

    function safeParseJson(raw, fallback) {
        if (!raw) {
            return fallback;
        }

        try {
            return JSON.parse(raw);
        } catch (error) {
            return fallback;
        }
    }

    function normalizeKeyword(value) {
        return (value || "").trim();
    }

    function initAutocomplete(form) {
        const input = form.querySelector("[data-search-input='true']");
        const dropdown = form.querySelector("[data-search-dropdown='true']");
        const popoverUrl = form.dataset.searchPopoverUrl;
        const suggestionsUrl = form.dataset.searchSuggestionsUrl;
        const clearUrl = form.dataset.searchClearUrl;
        const searchUserKey = form.dataset.searchUserKey || "guest";
        const backdrop = document.querySelector("[data-search-backdrop='true']");
        const recentJson = form.querySelector("[data-search-recent-json]");

        if (!input || !dropdown || !popoverUrl) {
            return;
        }

        let hotLoaded = false;
        let hotLoading = false;
        let panelInput = null;
        let suppressClose = false;
        let suppressCloseTimer = null;
        let suggestionItems = [];
        let suggestionQuery = "";
        let suggestionLoading = false;
        let suggestionRequestSeq = 0;
        let suggestionTimer = null;
        const localRecentKey = `fivefood_recent_searches:${searchUserKey}`;
        const legacyRecentKey = searchUserKey === "guest"
            ? "fivefood_recent_searches:anonymous"
            : `fivefood_recent_searches:${searchUserKey.replace(/^user:/, "")}`;
        let recentSearches = safeParseJson(recentJson ? recentJson.textContent : "[]", []);
        let storedRecentSearches = [];

        if (!Array.isArray(recentSearches)) {
            recentSearches = [];
        }

        try {
            const parsedStoredRecentSearches = safeParseJson(window.localStorage.getItem(localRecentKey), []);
            storedRecentSearches = Array.isArray(parsedStoredRecentSearches) ? parsedStoredRecentSearches : [];
            if (!storedRecentSearches.length) {
                const legacyStoredRecentSearches = safeParseJson(window.localStorage.getItem(legacyRecentKey), []);
                if (Array.isArray(legacyStoredRecentSearches) && legacyStoredRecentSearches.length) {
                    storedRecentSearches = legacyStoredRecentSearches;
                    window.localStorage.setItem(localRecentKey, JSON.stringify(storedRecentSearches));
                    window.localStorage.removeItem(legacyRecentKey);
                }
            }
        } catch (error) {
            storedRecentSearches = [];
        }

        recentSearches = recentSearches
            .concat(storedRecentSearches)
            .map((item) => normalizeKeyword(item))
            .filter((item, index, array) => Boolean(item) && array.indexOf(item) === index)
            .slice(0, RECENT_LIMIT);

        function persistRecentSearches() {
            try {
                window.localStorage.setItem(localRecentKey, JSON.stringify(recentSearches));
            } catch (error) {
                // Ignore storage errors and keep the session-backed flow working.
            }
        }

        function setOpen(isOpen) {
            dropdown.hidden = !isOpen;
            form.classList.toggle("is-open", isOpen);
            if (backdrop) {
                backdrop.hidden = !isOpen;
            }
        }

        function clearResults() {
            dropdown.innerHTML = "";
        }

        function holdPopoverOpen(duration) {
            suppressClose = true;
            if (suppressCloseTimer) {
                window.clearTimeout(suppressCloseTimer);
            }
            suppressCloseTimer = window.setTimeout(() => {
                suppressClose = false;
                suppressCloseTimer = null;
            }, typeof duration === "number" ? duration : 250);
        }

        function submitForm() {
            if (typeof form.requestSubmit === "function") {
                form.requestSubmit();
                return;
            }

            form.submit();
        }

        function syncSearchInputs(value, sourceInput) {
            const normalized = value != null ? String(value) : "";
            if (sourceInput !== input) {
                input.value = normalized;
            }
            if (panelInput && sourceInput !== panelInput) {
                panelInput.value = normalized;
            }
        }

        function submitCurrentQuery(sourceInput, explicitValue) {
            const isInputLike = sourceInput && typeof sourceInput === "object" && "value" in sourceInput;
            const activeInput = isInputLike ? sourceInput : (panelInput || input);
            const rawValue = typeof explicitValue === "string"
                ? explicitValue
                : (isInputLike ? activeInput.value : sourceInput);
            const value = normalizeKeyword(rawValue || (activeInput ? activeInput.value : ""));
            if (!value) {
                return;
            }

            syncSearchInputs(value, activeInput);
            recentSearches = [value].concat(recentSearches.filter((item) => item !== value)).slice(0, RECENT_LIMIT);
            persistRecentSearches();
            clearResults();
            setOpen(false);
            submitForm();
        }

        function createChipButton(item, extraClass) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = `site-search__chip ${extraClass || ""}`.trim();
            button.textContent = item.label || item.value || "";
            button.addEventListener("mousedown", (event) => {
                event.preventDefault();
                submitCurrentQuery(panelInput || input, item.value || item.label || "");
            });
            return button;
        }

        function createSuggestionButton(item) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "site-search__suggestion";

            const icon = document.createElement("span");
            icon.className = "site-search__suggestion-icon";
            icon.setAttribute("aria-hidden", "true");
            icon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path></svg>';
            button.appendChild(icon);

            const body = document.createElement("span");
            body.className = "site-search__suggestion-body";

            const title = document.createElement("span");
            title.className = "site-search__suggestion-title";
            title.textContent = item.label || item.value || "";
            body.appendChild(title);

            if (item.meta) {
                const meta = document.createElement("span");
                meta.className = "site-search__suggestion-meta";
                meta.textContent = item.meta;
                body.appendChild(meta);
            }

            button.appendChild(body);

            button.addEventListener("mousedown", (event) => {
                event.preventDefault();
                submitCurrentQuery(panelInput || input, item.value || item.label || "");
            });

            return button;
        }

        function createSearchKeywordButton(keyword) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "site-search__suggestion site-search__suggestion--search";

            const icon = document.createElement("span");
            icon.className = "site-search__suggestion-icon";
            icon.setAttribute("aria-hidden", "true");
            icon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path></svg>';
            button.appendChild(icon);

            const body = document.createElement("span");
            body.className = "site-search__suggestion-body";

            const title = document.createElement("span");
            title.className = "site-search__suggestion-title";
            title.textContent = `Tìm kiếm "${keyword}"`;
            body.appendChild(title);

            button.appendChild(body);

            button.addEventListener("mousedown", (event) => {
                event.preventDefault();
                submitCurrentQuery(panelInput || input, keyword);
            });

            return button;
        }

        function createSection(title, actionLabel, actionHandler) {
            const section = document.createElement("section");
            section.className = "site-search__section";

            const header = document.createElement("div");
            header.className = "site-search__section-head";

            const heading = document.createElement("h3");
            heading.className = "site-search__section-title";
            heading.textContent = title;
            header.appendChild(heading);

            if (actionLabel && typeof actionHandler === "function") {
                const action = document.createElement("button");
                action.type = "button";
                action.className = "site-search__section-action";
                action.textContent = actionLabel;
                action.addEventListener("mousedown", (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    suppressClose = true;
                });
                action.addEventListener("click", (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    actionHandler();
                });
                header.appendChild(action);
            }

            section.appendChild(header);
            return section;
        }

        function createEmptyHint(message) {
            const empty = document.createElement("div");
            empty.className = "site-search__empty site-search__empty--inline";
            empty.textContent = message;
            return empty;
        }

        function renderEmptyPanel(message) {
            clearResults();

            const empty = document.createElement("div");
            empty.className = "site-search__empty";
            empty.textContent = message;
            dropdown.appendChild(empty);
            setOpen(true);
        }

        function scheduleFetchSearchSuggestions(query) {
            const normalizedQuery = normalizeKeyword(query);

            if (suggestionTimer) {
                window.clearTimeout(suggestionTimer);
            }

            if (!normalizedQuery || !suggestionsUrl) {
                suggestionQuery = normalizedQuery;
                suggestionItems = [];
                suggestionLoading = false;
                if (!dropdown.hidden) {
                    renderPopoverPanel();
                }
                return;
            }

            suggestionQuery = normalizedQuery;
            suggestionLoading = true;
            if (!dropdown.hidden) {
                renderPopoverPanel();
            }

            suggestionTimer = window.setTimeout(() => {
                fetchSearchSuggestions(normalizedQuery);
            }, 150);
        }

        function fetchSearchSuggestions(query) {
            const normalizedQuery = normalizeKeyword(query);
            if (!suggestionsUrl || !normalizedQuery) {
                return;
            }

            const requestSeq = ++suggestionRequestSeq;
            suggestionQuery = normalizedQuery;

            const url = new URL(suggestionsUrl, window.location.origin);
            url.searchParams.set("q", normalizedQuery);
            url.searchParams.set("limit", "5");

            fetch(url.toString(), {
                headers: { Accept: "application/json" },
            })
                .then((response) => {
                    if (!response.ok) {
                        return [];
                    }

                    return response.json().then((payload) => (Array.isArray(payload.suggestions) ? payload.suggestions : []));
                })
                .then((results) => {
                    if (requestSeq !== suggestionRequestSeq) {
                        return;
                    }

                    suggestionItems = results.slice(0, 5);
                    suggestionLoading = false;

                    if (!dropdown.hidden) {
                        renderPopoverPanel();
                    }
                })
                .catch(() => {
                    if (requestSeq !== suggestionRequestSeq) {
                        return;
                    }

                    suggestionItems = [];
                    suggestionLoading = false;

                    if (!dropdown.hidden) {
                        renderPopoverPanel();
                    }
                });
        }

        function renderPopoverPanel() {
            clearResults();
            panelInput = null;

            const wrapper = document.createElement("div");
            wrapper.className = "site-search__popover";

            const closeButton = document.createElement("button");
            closeButton.type = "button";
            closeButton.className = "site-search__close";
            closeButton.setAttribute("aria-label", "Đóng tìm kiếm");
            closeButton.textContent = "×";
            closeButton.addEventListener("click", () => {
                setOpen(false);
                input.blur();
            });
            wrapper.appendChild(closeButton);

            const panel = document.createElement("div");
            panel.className = "site-search__popover-panel";

            const panelSearch = document.createElement("div");
            panelSearch.className = "site-search__panel-search";

            const panelSearchIcon = document.createElement("span");
            panelSearchIcon.className = "site-search__panel-search-icon";
            panelSearchIcon.setAttribute("aria-hidden", "true");
            panelSearchIcon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path></svg>';
            panelSearch.appendChild(panelSearchIcon);

            panelInput = document.createElement("input");
            panelInput.type = "search";
            panelInput.className = "site-search__panel-input";
            panelInput.value = input.value;
            panelInput.placeholder = input.getAttribute("placeholder") || "";
            panelInput.setAttribute("aria-label", input.getAttribute("aria-label") || "Tìm món ăn hoặc nhà hàng");
            panelInput.autocomplete = "off";
            panelInput.autocapitalize = "off";
            panelInput.autocorrect = "off";
            panelInput.spellcheck = false;
            panelInput.addEventListener("input", () => {
                syncSearchInputs(panelInput.value, panelInput);
                scheduleFetchSearchSuggestions(panelInput.value);
            });
            panelInput.addEventListener("keydown", (event) => {
                if (event.key === "Enter") {
                    event.preventDefault();
                    submitCurrentQuery(panelInput);
                }
            });
            panelInput.addEventListener("blur", () => {
                window.setTimeout(() => {
                    if (suppressClose) {
                        return;
                    }
                    if (!form.matches(":focus-within")) {
                        setOpen(false);
                    }
                }, 120);
            });
            panelSearch.appendChild(panelInput);
            panel.appendChild(panelSearch);

            const currentQuery = normalizeKeyword(panelInput.value || input.value);
            if (currentQuery.length) {
                const suggestionSection = createSection("GỢI Ý TÌM KIẾM");
                const suggestionBody = document.createElement("div");
                suggestionBody.className = "site-search__suggestions";

                if (suggestionLoading && suggestionQuery === currentQuery) {
                    const loading = document.createElement("div");
                    loading.className = "site-search__loading";
                    loading.textContent = "Đang tìm gợi ý...";
                    suggestionBody.appendChild(loading);
                } else if (suggestionQuery === currentQuery && suggestionItems.length) {
                    suggestionItems.forEach((item) => {
                        suggestionBody.appendChild(createSuggestionButton(item));
                    });
                }

                suggestionBody.appendChild(createSearchKeywordButton(currentQuery));

                if (suggestionBody.childElementCount) {
                    suggestionSection.appendChild(suggestionBody);
                    panel.appendChild(suggestionSection);
                }
            }

            if (!currentQuery.length && recentSearches.length) {
                const recentSection = createSection("TÌM KIẾM GẦN ĐÂY", "Xoá hết", () => {
                    holdPopoverOpen(300);
                    recentSearches = [];
                    persistRecentSearches();
                    renderPopoverPanel();
                    setOpen(true);
                    window.setTimeout(() => {
                        if (panelInput && panelInput.isConnected) {
                            panelInput.focus({ preventScroll: true });
                        }
                    }, 0);
                    if (clearUrl) {
                        fetch(clearUrl, {
                            method: "POST",
                            headers: {
                                "X-Requested-With": "fetch",
                            },
                        }).catch(() => {});
                    }
                });
                const chips = document.createElement("div");
                chips.className = "site-search__chips";
                recentSearches.forEach((keyword) => {
                    chips.appendChild(createChipButton({ value: keyword }, "site-search__chip--recent"));
                });
                recentSection.appendChild(chips);
                panel.appendChild(recentSection);
            }

            if (!currentQuery.length) {
                const hotSection = createSection("MÓN GÌ ĐANG HOT");
                const hotBody = document.createElement("div");
                hotBody.className = "site-search__chips site-search__chips--hot";

                const cachedHot = Array.isArray(window.__fiveFoodHotSearches) ? window.__fiveFoodHotSearches : [];
                if (hotLoading && !hotLoaded) {
                    const loading = document.createElement("div");
                    loading.className = "site-search__loading";
                    loading.textContent = "Đang tải món hot...";
                    hotBody.appendChild(loading);
                } else if (cachedHot.length) {
                    cachedHot.slice(0, HOT_LIMIT).forEach((item) => {
                        hotBody.appendChild(createChipButton(item, "site-search__chip--hot"));
                    });
                } else if (hotLoaded) {
                    const emptyHot = document.createElement("div");
                    emptyHot.className = "site-search__empty site-search__empty--inline";
                    emptyHot.textContent = "Chưa có dữ liệu món hot trong 7 ngày gần đây.";
                    hotBody.appendChild(emptyHot);
                } else {
                    const loading = document.createElement("div");
                    loading.className = "site-search__loading";
                    loading.textContent = "Đang tải món hot...";
                    hotBody.appendChild(loading);
                }

                hotSection.appendChild(hotBody);
                panel.appendChild(hotSection);
            }

            wrapper.appendChild(panel);
            dropdown.appendChild(wrapper);
            setOpen(true);

            window.setTimeout(() => {
                if (panelInput && panelInput.isConnected) {
                    panelInput.focus({ preventScroll: true });
                }
            }, 0);
        }

        function fetchHotKeywords() {
            if (hotLoaded || hotLoading) {
                if (!dropdown.hidden) {
                    renderPopoverPanel();
                }
                return;
            }

            hotLoading = true;
            const url = new URL(popoverUrl, window.location.origin);
            url.searchParams.set("limit", String(HOT_LIMIT));

            fetch(url.toString(), {
                headers: { Accept: "application/json" },
            })
                .then((response) => {
                    if (!response.ok) {
                        return [];
                    }

                    return response.json().then((payload) => (Array.isArray(payload.hot) ? payload.hot : []));
                })
                .then((results) => {
                    hotLoaded = true;
                    hotLoading = false;
                    window.__fiveFoodHotSearches = results.slice(0, HOT_LIMIT);

                    if (!dropdown.hidden) {
                        renderPopoverPanel();
                    }
                })
                .catch(() => {
                    hotLoaded = true;
                    hotLoading = false;
                    window.__fiveFoodHotSearches = [];
                    if (!dropdown.hidden) {
                        renderPopoverPanel();
                    }
                });
        }

        function openPopoverIfNeeded() {
            renderPopoverPanel();
            fetchHotKeywords();
            scheduleFetchSearchSuggestions(panelInput ? panelInput.value : input.value);
        }

        input.addEventListener("input", () => {
            syncSearchInputs(input.value, input);
            if (!dropdown.hidden) {
                scheduleFetchSearchSuggestions(input.value);
            }
        });

        input.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                submitCurrentQuery(input);
            }
        });

        input.addEventListener("focus", openPopoverIfNeeded);
        input.addEventListener("click", openPopoverIfNeeded);

        input.addEventListener("blur", () => {
            window.setTimeout(() => {
                if (suppressClose) {
                    return;
                }
                if (!form.matches(":focus-within")) {
                    setOpen(false);
                }
            }, 120);
        });

        if (backdrop) {
            backdrop.addEventListener("click", () => {
                if (suppressClose) {
                    return;
                }
                setOpen(false);
                input.blur();
            });
        }

        document.addEventListener("click", (event) => {
            if (suppressClose) {
                return;
            }
            if (form.contains(event.target) || (backdrop && backdrop.contains(event.target))) {
                return;
            }

            if (!form.matches(":focus-within")) {
                setOpen(false);
            }
        });

        if (normalizeKeyword(input.value).length) {
            syncSearchInputs(input.value, input);
        }
    }

    function initAll() {
        document.querySelectorAll(AUTOCOMPLETE_SELECTOR).forEach(initAutocomplete);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initAll);
    } else {
        initAll();
    }
})();
