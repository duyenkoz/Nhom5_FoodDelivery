(function () {
    function initLiveSearch(root) {
        const forms = (root || document).querySelectorAll("form[data-live-search-form]");

        forms.forEach((form) => {
            if (form.dataset.liveSearchBound === "1") {
                return;
            }
            form.dataset.liveSearchBound = "1";

            const searchInput = form.querySelector('input[type="search"]');
            const targetSelector = form.dataset.liveSearchTarget;
            const target = targetSelector ? document.querySelector(targetSelector) : null;

            if (!searchInput || !target) {
                return;
            }

            let timer = null;

            function syncFromResponse(html) {
                const parser = new DOMParser();
                const doc = parser.parseFromString(html, "text/html");
                const nextTarget = targetSelector ? doc.querySelector(targetSelector) : null;

                if (!nextTarget) {
                    return;
                }

                target.innerHTML = nextTarget.innerHTML;
                initLiveSearch(target);
            }

            async function fetchResults() {
                const url = new URL(form.action, window.location.origin);
                const params = new URLSearchParams(new FormData(form));
                params.forEach((value, key) => url.searchParams.set(key, value));
                const selectionStart = searchInput.selectionStart;
                const selectionEnd = searchInput.selectionEnd;
                const selectionDirection = searchInput.selectionDirection || "none";

                try {
                    form.setAttribute("aria-busy", "true");
                    const response = await fetch(url.toString(), {
                        headers: {
                            "X-Requested-With": "XMLHttpRequest",
                        },
                        credentials: "same-origin",
                    });

                    if (!response.ok) {
                        return;
                    }

                    const html = await response.text();
                    syncFromResponse(html);
                    requestAnimationFrame(() => {
                        if (!searchInput.isConnected) {
                            return;
                        }
                        searchInput.focus({ preventScroll: true });
                        if (
                            typeof selectionStart === "number"
                            && typeof selectionEnd === "number"
                            && typeof searchInput.setSelectionRange === "function"
                        ) {
                            searchInput.setSelectionRange(selectionStart, selectionEnd, selectionDirection);
                        }
                    });
                    if (window.history && window.history.replaceState) {
                        window.history.replaceState({}, "", url.toString());
                    }
                } catch (error) {
                    return;
                } finally {
                    form.removeAttribute("aria-busy");
                }
            }

            function scheduleFetch() {
                clearTimeout(timer);
                timer = setTimeout(fetchResults, 250);
            }

            searchInput.addEventListener("keyup", scheduleFetch);
            searchInput.addEventListener("input", scheduleFetch);
            form.addEventListener("submit", (event) => {
                event.preventDefault();
                fetchResults();
            });
        });
    }

    document.addEventListener("DOMContentLoaded", () => initLiveSearch(document));
})();
