(function () {
    function initLoadMore(section) {
        const button = section.querySelector("[data-load-more-button='true']");
        const grid = section.querySelector("[data-load-more-grid='true']");

        if (!button || !grid) {
            return;
        }

        let isLoading = false;

        button.addEventListener("click", async function () {
            const loadMoreUrl = button.dataset.loadMoreUrl;
            if (!loadMoreUrl || isLoading) {
                return;
            }

            isLoading = true;
            button.disabled = true;
            button.textContent = "Đang tải...";

            try {
                const response = await fetch(loadMoreUrl, {
                    headers: { Accept: "application/json" },
                });

                if (!response.ok) {
                    throw new Error("load_more_failed");
                }

                const payload = await response.json();
                if (payload.html) {
                    grid.insertAdjacentHTML("beforeend", payload.html);
                }

                if (payload.has_more && payload.load_more_url) {
                    button.dataset.loadMoreUrl = payload.load_more_url;
                    button.disabled = false;
                    button.textContent = "Xem thêm";
                } else {
                    const footer = button.closest(".home-section__footer");
                    if (footer) {
                        footer.remove();
                    } else {
                        button.remove();
                    }
                }
            } catch (error) {
                button.disabled = false;
                button.textContent = "Thử lại";
            } finally {
                isLoading = false;
            }
        });
    }

    function initAll() {
        document.querySelectorAll("[data-load-more-list='true']").forEach(initLoadMore);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initAll);
    } else {
        initAll();
    }
})();
