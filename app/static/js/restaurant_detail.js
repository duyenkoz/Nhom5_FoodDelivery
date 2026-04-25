(function () {
    const ROOT_SELECTOR = "[data-restaurant-detail='true']";

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

    function formatPrice(value) {
        const amount = Number(value || 0);
        return `${amount.toLocaleString("vi-VN")}đ`;
    }

    function escapeHtml(value) {
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function normalizeText(value) {
        return String(value || "")
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "")
            .replace(/đ/g, "d")
            .replace(/Đ/g, "D")
            .trim()
            .toLowerCase();
    }

    function initRestaurantDetail(root) {
        const searchInput = root.querySelector("[data-restaurant-search='true']");
        const dishCards = Array.from(root.querySelectorAll("[data-dish-card='true']"));
        const menuSections = Array.from(root.querySelectorAll("[data-menu-section]"));
        const categoryTabs = Array.from(root.querySelectorAll("[data-category-tab]"));
        const searchEmpty = root.querySelector("[data-search-empty='true']");
        const cartItemsContainer = root.querySelector("[data-cart-items='true']");
        const cartTotal = root.querySelector("[data-cart-total='true']");
        const cartOrdersCta = root.querySelector("[data-cart-orders-cta='true']");
        const modal = document.querySelector("[data-dish-modal='true']");
        const cartConfirmModal = document.querySelector("[data-cart-confirm-modal='true']");
        const similarToggle = root.querySelector("[data-similar-toggle='true']");
        const similarSection = document.getElementById("similarRestaurants");
        const similarTrack = root.querySelector("[data-similar-track='true']");
        const similarControls = root.querySelector("[data-similar-controls='true']");
        const similarPrevButton = root.querySelector("[data-similar-prev='true']");
        const similarNextButton = root.querySelector("[data-similar-next='true']");
        const reviewOpenButton = root.querySelector("[data-open-restaurant-reviews='true']");
        const reviewModal = document.querySelector("[data-restaurant-review-modal='true']");
        const reviewAiTrigger = document.querySelector("[data-review-ai-trigger='true']");
        const reviewAiStatus = document.querySelector("[data-review-ai-status='true']");
        const reviewAiError = document.querySelector("[data-review-ai-error='true']");
        const reviewAiSummary = document.querySelector("[data-review-ai-summary='true']");
        const reviewAiToggle = document.querySelector("[data-review-ai-toggle='true']");
        const reviewAiBody = document.querySelector("[data-review-ai-body='true']");
        const reviewAiOverview = document.querySelector("[data-review-ai-overview='true']");
        const reviewAiStrengths = document.querySelector("[data-review-ai-strengths='true']");
        const reviewAiImprovements = document.querySelector("[data-review-ai-improvements='true']");
        const reviewAiMeta = document.querySelector("[data-review-ai-meta='true']");

        const dishes = safeParseJson(
            (root.querySelector("[data-restaurant-dishes-json]") || {}).textContent,
            []
        );
        let cart = safeParseJson(
            (root.querySelector("[data-restaurant-cart-json]") || {}).textContent,
            { items: [], total_amount: 0, total_amount_text: formatPrice(0), is_empty: true }
        );

        const cartCleared = new URLSearchParams(window.location.search).get("cart_cleared") === "1";
        if (cartCleared) {
            window.AppToast?.success("Đã xoá hết món khỏi giỏ hàng.");
            const nextUrl = new URL(window.location.href);
            nextUrl.searchParams.delete("cart_cleared");
            window.history.replaceState({}, "", `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`);
        }

        const dishById = new Map(dishes.map((dish) => [Number(dish.dish_id), dish]));
        const cartAddUrl = root.dataset.cartAddUrl;
        const cartUpdateUrlTemplate = root.dataset.cartUpdateUrlTemplate || "";
        const reviewAiSummaryUrl = root.dataset.aiReviewSummaryUrl || "";

        let activeCategory = categoryTabs.length ? categoryTabs[0].dataset.categoryTab : "";
        let modalDishId = null;
        let modalQuantity = 1;
        let modalMode = "add";
        let pendingZeroQuantitySubmit = null;
        let syncSimilarSliderState = function () {};
        let reviewAiSummaryCache = null;
        let reviewAiSummaryRequest = null;
        let reviewAiCollapsed = false;

        function getSimilarScrollStep() {
            if (!similarTrack) {
                return 0;
            }

            const firstCard = similarTrack.querySelector(".restaurant-similar__card");
            if (!firstCard) {
                return similarTrack.clientWidth;
            }

            const trackStyles = window.getComputedStyle(similarTrack);
            const gap = parseFloat(trackStyles.columnGap || trackStyles.gap || "0") || 0;
            return firstCard.getBoundingClientRect().width + gap;
        }

        function initSimilarSlider() {
            if (!similarTrack) {
                return;
            }

            if (similarPrevButton) {
                similarPrevButton.setAttribute("aria-label", "Xem nha hang tuong tu truoc do");
            }

            if (similarNextButton) {
                similarNextButton.setAttribute("aria-label", "Xem them nha hang tuong tu");
            }

            let isPointerDown = false;
            let startX = 0;
            let startScrollLeft = 0;
            let moved = false;
            let pendingLinkHref = "";

            function updateState() {
                if (!similarTrack) {
                    return;
                }

                const maxScrollLeft = Math.max(0, similarTrack.scrollWidth - similarTrack.clientWidth);
                const canScroll = maxScrollLeft > 8;
                const isAtStart = similarTrack.scrollLeft <= 8;
                const isAtEnd = similarTrack.scrollLeft >= maxScrollLeft - 8;

                if (similarControls) {
                    similarControls.hidden = !canScroll;
                }

                if (similarPrevButton) {
                    similarPrevButton.disabled = !canScroll || isAtStart;
                }

                if (similarNextButton) {
                    similarNextButton.disabled = !canScroll || isAtEnd;
                }
            }

            function isInteractiveTarget(target) {
                return Boolean(target.closest("button, input, select, textarea, label"));
            }

            similarTrack.addEventListener("pointerdown", function (event) {
                if (event.pointerType === "mouse" && event.button !== 0) {
                    return;
                }

                if (isInteractiveTarget(event.target)) {
                    return;
                }

                isPointerDown = true;
                moved = false;
                startX = event.clientX;
                startScrollLeft = similarTrack.scrollLeft;
                pendingLinkHref = "";

                const link = event.target.closest("a[href]");
                if (link) {
                    pendingLinkHref = link.href || "";
                }

                similarTrack.classList.add("is-dragging");
                similarTrack.setPointerCapture(event.pointerId);
            });

            similarTrack.addEventListener("pointermove", function (event) {
                if (!isPointerDown) {
                    return;
                }

                const deltaX = event.clientX - startX;
                if (Math.abs(deltaX) > 4) {
                    moved = true;
                }

                similarTrack.scrollLeft = startScrollLeft - deltaX;
            });

            function stopDragging(event) {
                if (!isPointerDown) {
                    return;
                }

                const shouldFollowLink = !moved && pendingLinkHref;
                isPointerDown = false;
                similarTrack.classList.remove("is-dragging");

                if (event && typeof event.pointerId !== "undefined") {
                    try {
                        similarTrack.releasePointerCapture(event.pointerId);
                    } catch (error) {
                        // Ignore release errors when pointer capture is already cleared.
                    }
                }

                if (shouldFollowLink) {
                    window.location.href = pendingLinkHref;
                }

                pendingLinkHref = "";
                moved = false;
            }

            if (similarPrevButton) {
                similarPrevButton.addEventListener("click", function () {
                    similarTrack.scrollBy({
                        left: -getSimilarScrollStep(),
                        behavior: "smooth",
                    });
                });
            }

            if (similarNextButton) {
                similarNextButton.addEventListener("click", function () {
                    similarTrack.scrollBy({
                        left: getSimilarScrollStep(),
                        behavior: "smooth",
                    });
                });
            }

            similarTrack.addEventListener("pointerup", stopDragging);
            similarTrack.addEventListener("pointercancel", stopDragging);
            similarTrack.addEventListener("lostpointercapture", stopDragging);
            similarTrack.addEventListener("scroll", updateState, { passive: true });
            window.addEventListener("resize", updateState);

            similarTrack.addEventListener("click", function (event) {
                if (!moved) {
                    return;
                }

                event.preventDefault();
                event.stopPropagation();
                moved = false;
            }, true);

            syncSimilarSliderState = updateState;
            updateState();
        }

        function setSimilarOpen(isOpen) {
            if (!similarToggle || !similarSection) {
                return;
            }

            similarSection.hidden = !isOpen;
            similarToggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
            similarToggle.classList.toggle("is-open", isOpen);

            if (isOpen) {
                window.requestAnimationFrame(syncSimilarSliderState);
            }
        }

        function openReviewModal() {
            if (!reviewModal) {
                return;
            }

            reviewModal.hidden = false;
            reviewModal.setAttribute("aria-hidden", "false");
            document.body.classList.add("is-modal-open");
            if (reviewOpenButton) {
                reviewOpenButton.setAttribute("aria-expanded", "true");
            }
        }

        function setReviewAiBusy(isBusy) {
            if (!reviewAiTrigger) {
                return;
            }

            const defaultText = reviewAiTrigger.dataset.defaultText || "Tóm tắt bằng AI";
            const loadingText = reviewAiTrigger.dataset.loadingText || "Đang tóm tắt...";
            reviewAiTrigger.disabled = Boolean(isBusy);
            reviewAiTrigger.setAttribute("aria-busy", isBusy ? "true" : "false");
            reviewAiTrigger.classList.toggle("is-loading", Boolean(isBusy));
            reviewAiTrigger.innerHTML = isBusy
                ? `<span aria-hidden="true">...</span><span>${escapeHtml(loadingText)}</span>`
                : `<span aria-hidden="true">AI</span><span>${escapeHtml(defaultText)}</span>`;
        }

        function hideReviewAiFeedback() {
            if (reviewAiStatus) {
                reviewAiStatus.hidden = true;
                reviewAiStatus.textContent = "";
            }
            if (reviewAiError) {
                reviewAiError.hidden = true;
                reviewAiError.textContent = "";
            }
        }

        function renderReviewAiList(target, items, emptyText) {
            if (!target) {
                return;
            }

            if (!Array.isArray(items) || !items.length) {
                target.innerHTML = `<li class="restaurant-review-ai__empty-item">${escapeHtml(emptyText)}</li>`;
                return;
            }

            target.innerHTML = items
                .map((item) => `<li>${escapeHtml(item)}</li>`)
                .join("");
        }

        function setReviewAiCollapsed(isCollapsed) {
            reviewAiCollapsed = Boolean(isCollapsed);

            if (reviewAiSummary) {
                reviewAiSummary.classList.toggle("is-collapsed", reviewAiCollapsed);
            }

            if (reviewAiBody) {
                reviewAiBody.hidden = reviewAiCollapsed;
            }

            if (reviewAiToggle) {
                reviewAiToggle.setAttribute("aria-expanded", reviewAiCollapsed ? "false" : "true");
                reviewAiToggle.setAttribute(
                    "aria-label",
                    reviewAiCollapsed ? "Mở rộng tóm tắt AI" : "Thu gọn tóm tắt AI"
                );
            }
        }

        function renderReviewAiSummary(payload) {
            if (!reviewAiSummary) {
                return;
            }

            const summary = payload && payload.summary ? payload.summary : {};
            hideReviewAiFeedback();
            reviewAiSummary.hidden = false;
            setReviewAiCollapsed(false);

            if (reviewAiOverview) {
                reviewAiOverview.textContent = summary.overview || "";
            }

            renderReviewAiList(
                reviewAiStrengths,
                summary.strengths || [],
                "Chưa có đủ dữ liệu để rút ra điểm nổi bật rõ ràng."
            );
            renderReviewAiList(
                reviewAiImprovements,
                summary.improvements || [],
                "Chưa có góp ý nổi bật cần ưu tiên trong nhóm đánh giá này."
            );

            if (reviewAiMeta) {
                reviewAiMeta.textContent = `Dựa trên ${payload.review_count_used || 0} đánh giá mới nhất.`;
            }
        }

        function showReviewAiError(message) {
            if (!reviewAiError) {
                return;
            }

            if (reviewAiStatus) {
                reviewAiStatus.hidden = true;
                reviewAiStatus.textContent = "";
            }
            reviewAiError.hidden = false;
            reviewAiError.textContent = message || "Chưa thể tạo tóm tắt AI lúc này.";
        }

        function fetchReviewAiSummary() {
            if (!reviewAiSummaryUrl || !reviewAiTrigger) {
                return Promise.resolve();
            }

            if (reviewAiSummaryCache) {
                renderReviewAiSummary(reviewAiSummaryCache);
                return Promise.resolve(reviewAiSummaryCache);
            }

            if (reviewAiSummaryRequest) {
                return reviewAiSummaryRequest;
            }

            if (reviewAiStatus) {
                reviewAiStatus.hidden = false;
                reviewAiStatus.textContent = "Đang tổng hợp đánh giá từ khách hàng...";
            }
            if (reviewAiSummary) {
                reviewAiSummary.hidden = true;
            }
            if (reviewAiError) {
                reviewAiError.hidden = true;
                reviewAiError.textContent = "";
            }

            setReviewAiBusy(true);
            reviewAiSummaryRequest = requestJson(reviewAiSummaryUrl, {})
                .then(({ ok, data }) => {
                    if (!ok || !data.ok) {
                        throw new Error(data.message || "Chưa thể tạo tóm tắt AI lúc này.");
                    }

                    reviewAiSummaryCache = data;
                    renderReviewAiSummary(data);
                    return data;
                })
                .catch((error) => {
                    showReviewAiError(error.message || "Chưa thể tạo tóm tắt AI lúc này.");
                    throw error;
                })
                .finally(() => {
                    setReviewAiBusy(false);
                    reviewAiSummaryRequest = null;
                });

            return reviewAiSummaryRequest;
        }

        function closeReviewModal() {
            if (!reviewModal) {
                return;
            }

            reviewModal.hidden = true;
            reviewModal.setAttribute("aria-hidden", "true");
            document.body.classList.remove("is-modal-open");
            if (reviewOpenButton) {
                reviewOpenButton.setAttribute("aria-expanded", "false");
            }
        }

        function buildCartUpdateUrl(dishId) {
            return cartUpdateUrlTemplate.replace(/0\/?$/, `${dishId}`);
        }

        function syncCartCtaState() {
            if (!cartOrdersCta) {
                return;
            }

            const isEmpty = !Array.isArray(cart.items) || cart.items.length === 0;
            cartOrdersCta.disabled = isEmpty;
            cartOrdersCta.setAttribute("aria-disabled", isEmpty ? "true" : "false");
            cartOrdersCta.classList.toggle("is-disabled", isEmpty);
        }

        function openZeroQuantityConfirm() {
            if (!cartConfirmModal) {
                return;
            }

            cartConfirmModal.hidden = false;
            cartConfirmModal.setAttribute("aria-hidden", "false");
        }

        function closeZeroQuantityConfirm() {
            if (!cartConfirmModal) {
                return;
            }

            cartConfirmModal.hidden = true;
            cartConfirmModal.setAttribute("aria-hidden", "true");
        }

        function promptCartItemRemoval(dishId, note) {
            pendingZeroQuantitySubmit = {
                dishId: Number(dishId),
                note: note || "",
            };

            if (cartConfirmModal) {
                const confirmMessage = cartConfirmModal.querySelector("[data-cart-confirm-message='true']");
                if (confirmMessage) {
                    confirmMessage.textContent = "Bạn có chắc sẽ xoá món này khỏi giỏ hàng?";
                }
            }

            openZeroQuantityConfirm();
        }

        function setCartState(nextCart) {
            cart = nextCart || { items: [], total_amount: 0, total_amount_text: formatPrice(0), is_empty: true };
            renderCart();
        }

        function renderCart() {
            if (!cartItemsContainer || !cartTotal) {
                return;
            }

            cartTotal.textContent = cart.total_amount_text || formatPrice(cart.total_amount);
            syncCartCtaState();

            if (!Array.isArray(cart.items) || !cart.items.length) {
                cartItemsContainer.innerHTML = '<div class="restaurant-cart__empty">Giỏ hàng đang trống. Hãy chọn món từ thực đơn của nhà hàng này.</div>';
                return;
            }

            cartItemsContainer.innerHTML = cart.items.map((item) => {
                const imageSrc = /^(https?:)?\/\//.test(item.image_path)
                    ? item.image_path
                    : `/static/${item.image_path}`;
                const noteHtml = item.note ? `
                    <div class="restaurant-cart-item__note">
                        <span class="restaurant-cart-item__note-icon" aria-hidden="true">
                            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
                                <path d="M7 4.75h7.55L18.75 9v10.25A1.75 1.75 0 0 1 17 21H7a1.75 1.75 0 0 1-1.75-1.75V6.5A1.75 1.75 0 0 1 7 4.75Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>
                                <path d="M14.5 4.75V9h4.25" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
                                <path d="M8.75 12.25h6.5M8.75 15.25h4.75" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>
                            </svg>
                        </span>
                        <span class="restaurant-cart-item__note-text">${escapeHtml(item.note)}</span>
                    </div>
                ` : "";

                return `
                    <article class="restaurant-cart-item">
                        <img class="restaurant-cart-item__image" src="${escapeHtml(imageSrc)}" alt="${escapeHtml(item.name)}">
                        <div class="restaurant-cart-item__main">
                            <div class="restaurant-cart-item__name-row">
                                <strong>${escapeHtml(item.name)}</strong>
                                <div class="restaurant-cart-item__actions">
                                    <button type="button" class="restaurant-cart-item__edit" data-edit-cart-item="${item.dish_id}" aria-label="Chỉnh sửa món">
                                        <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                                            <path d="M3 17.25V21h3.75L17.8 9.94l-3.75-3.75L3 17.25Zm2.92 2.33H5v-.92l8.06-8.06.92.92L5.92 19.58ZM20.71 7.04a1.003 1.003 0 0 0 0-1.42L18.37 3.29a1.003 1.003 0 0 0-1.42 0L15.13 5.1l3.75 3.75 1.83-1.81Z"></path>
                                            <path d="M3 22h18v-2H3v2Z"></path>
                                        </svg>
                                    </button>
                                    <button type="button" class="restaurant-cart-item__delete" data-delete-cart-item="${item.dish_id}" aria-label="Xóa món khỏi giỏ">
                                        <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                                            <path d="M9 3h6l1 2h5v2H3V5h5l1-2Zm1 6h2v8h-2V9Zm4 0h2v8h-2V9ZM6 9h2v8H6V9Zm1 12c-1.1 0-2-.9-2-2V8h14v11c0 1.1-.9 2-2 2H7Z"></path>
                                        </svg>
                                    </button>
                                </div>
                            </div>
                            ${noteHtml}
                            <div class="restaurant-cart-item__meta">
                                <strong>${escapeHtml(item.price_text)}</strong>
                                <div class="qty-picker" data-cart-qty-picker="${item.dish_id}">
                                    <button type="button" data-cart-qty-minus="${item.dish_id}" aria-label="Giảm số lượng">-</button>
                                    <strong>${item.quantity}</strong>
                                    <button type="button" data-cart-qty-plus="${item.dish_id}" aria-label="Tăng số lượng">+</button>
                                </div>
                            </div>
                        </div>
                    </article>
                `;
            }).join("");
        }

        function syncCategoryTabs() {
            categoryTabs.forEach((tab) => {
                const isActive = tab.dataset.categoryTab === activeCategory;
                tab.classList.toggle("is-active", isActive);
                tab.setAttribute("aria-selected", isActive ? "true" : "false");
            });
        }

        function isDishAvailable(dish) {
            return Boolean(dish && dish.is_available);
        }

        function syncModalAvailability(dish) {
            if (!modal) {
                return;
            }

            const isAvailable = isDishAvailable(dish);
            const submitButton = modal.querySelector("[data-dish-modal-submit='true']");
            const minusButton = modal.querySelector("[data-modal-qty-minus='true']");
            const plusButton = modal.querySelector("[data-modal-qty-plus='true']");
            const noteField = modal.querySelector("[data-dish-modal-note='true']");

            if (submitButton) {
                submitButton.disabled = !isAvailable;
                submitButton.setAttribute("aria-disabled", isAvailable ? "false" : "true");
                submitButton.classList.toggle("is-sold-out", !isAvailable);
            }

            if (minusButton) {
                minusButton.disabled = !isAvailable;
            }

            if (plusButton) {
                plusButton.disabled = !isAvailable;
            }

            if (noteField) {
                noteField.disabled = !isAvailable;
            }
        }

        function applyFilters() {
            const query = normalizeText(searchInput ? searchInput.value : "");
            let visibleCount = 0;

            menuSections.forEach((section) => {
                let sectionVisibleCount = 0;

                Array.from(section.querySelectorAll("[data-dish-card='true']")).forEach((card) => {
                    const cardText = normalizeText(card.dataset.searchText || "");
                    const matchesQuery = !query || cardText.includes(query);
                    const isVisible = matchesQuery;
                    card.hidden = !isVisible;

                    if (isVisible) {
                        sectionVisibleCount += 1;
                        visibleCount += 1;
                    }
                });

                section.hidden = sectionVisibleCount === 0;
            });

            if (searchEmpty) {
                searchEmpty.hidden = visibleCount > 0;
            }
        }

        function updateModalSubmitLabel() {
            if (!modal || modalDishId == null) {
                return;
            }

            const dish = dishById.get(Number(modalDishId));
            const submitButton = modal.querySelector("[data-dish-modal-submit='true']");
            const qtyEl = modal.querySelector("[data-dish-modal-qty='true']");
            if (!dish || !submitButton || !qtyEl) {
                return;
            }

            qtyEl.textContent = String(modalQuantity);
            if (!isDishAvailable(dish)) {
                submitButton.textContent = "Hết món";
                return;
            }
            submitButton.textContent = `Thêm vào giỏ - ${formatPrice((dish.price || 0) * modalQuantity)}`;
        }

        function openDishModal(dishId, mode = "add") {
            if (!modal) {
                return;
            }

            const dish = dishById.get(Number(dishId));
            if (!dish) {
                return;
            }

            modalDishId = Number(dishId);
            modalMode = mode === "edit" ? "edit" : "add";
            pendingZeroQuantitySubmit = null;
            closeZeroQuantityConfirm();
            const cartItem = Array.isArray(cart.items) ? cart.items.find((item) => Number(item.dish_id) === modalDishId) : null;
            modalQuantity = cartItem ? Number(cartItem.quantity || 1) : 1;

            const imageEl = modal.querySelector("[data-dish-modal-image='true']");
            const titleEl = modal.querySelector("[data-dish-modal-title='true']");
            const priceEl = modal.querySelector("[data-dish-modal-price='true']");
            const descEl = modal.querySelector("[data-dish-modal-description='true']");
            const soldEl = modal.querySelector("[data-dish-modal-sold='true']");
            const noteEl = modal.querySelector("[data-dish-modal-note='true']");
            const qtyEl = modal.querySelector("[data-dish-modal-qty='true']");

            imageEl.src = /^(https?:)?\/\//.test(dish.image_path) ? dish.image_path : `/static/${dish.image_path}`;
            imageEl.alt = dish.name;
            titleEl.textContent = dish.name;
            priceEl.textContent = dish.price_text;
            descEl.textContent = dish.description;
            soldEl.textContent = `${dish.sold_count} đã bán`;
            noteEl.value = cartItem && cartItem.note ? cartItem.note : "";
            qtyEl.textContent = String(modalQuantity);

            syncModalAvailability(dish);
            updateModalSubmitLabel();
            modal.hidden = false;
            document.body.classList.add("is-modal-open");
        }

        function closeDishModal() {
            if (!modal) {
                return;
            }

            modal.hidden = true;
            document.body.classList.remove("is-modal-open");
            modalDishId = null;
            modalMode = "add";
            pendingZeroQuantitySubmit = null;
            closeZeroQuantityConfirm();
        }

        function requestJson(url, payload) {
            return fetch(url, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Accept: "application/json",
                },
                body: JSON.stringify(payload || {}),
            }).then((response) => response.json().then((data) => ({ ok: response.ok, data })));
        }

        function addDishToCart(dishId, quantity, note) {
            return requestJson(cartAddUrl, {
                dish_id: dishId,
                quantity: quantity,
                note: note || "",
            }).then(({ ok, data }) => {
                if (!ok || !data.ok) {
                    throw new Error(data.message || "Không thể thêm món vào giỏ.");
                }
                setCartState(data.cart);
                AppToast.success("Thêm món ăn vào giỏ thành công");
            });
        }

        function updateDishQuantity(dishId, quantity, note) {
            return requestJson(buildCartUpdateUrl(dishId), {
                quantity: quantity,
                note: note,
            }).then(({ ok, data }) => {
                if (!ok || !data.ok) {
                    throw new Error(data.message || "Không thể cập nhật giỏ hàng.");
                }
                setCartState(data.cart);
            });
        }

        categoryTabs.forEach((tab) => {
            tab.addEventListener("click", () => {
                activeCategory = tab.dataset.categoryTab || "";
                syncCategoryTabs();

                const section = root.querySelector(`[data-menu-section="${activeCategory}"]`);
                if (section) {
                    section.scrollIntoView({ behavior: "smooth", block: "start" });
                }
            });
        });

        initSimilarSlider();

        if (similarToggle && similarSection) {
            setSimilarOpen(false);
            similarToggle.addEventListener("click", () => {
                const isOpen = similarToggle.getAttribute("aria-expanded") === "true";
                setSimilarOpen(!isOpen);
            });
        }

        if (reviewOpenButton && reviewModal) {
            reviewOpenButton.addEventListener("click", openReviewModal);

            reviewModal.addEventListener("click", (event) => {
                if (event.target.closest("[data-close-restaurant-reviews='true']")) {
                    closeReviewModal();
                }
            });
        }

        if (reviewAiTrigger) {
            reviewAiTrigger.addEventListener("click", () => {
                fetchReviewAiSummary().catch(() => {});
            });
        }

        if (reviewAiToggle) {
            reviewAiToggle.addEventListener("click", () => {
                setReviewAiCollapsed(!reviewAiCollapsed);
            });
        }

        if (searchInput) {
            searchInput.addEventListener("input", applyFilters);
        }

        dishCards.forEach((card) => {
            const dishId = Number(card.dataset.dishId);

            card.addEventListener("click", (event) => {
                const addButton = event.target.closest("[data-add-dish]");
                if (addButton) {
                    event.stopPropagation();
                    if (!isDishAvailable(dishById.get(dishId))) {
                        return;
                    }
                    addDishToCart(dishId, 1, "").catch(() => {});
                    return;
                }

                openDishModal(dishId);
            });

            card.addEventListener("keydown", (event) => {
                if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    openDishModal(dishId);
                }
            });
        });

        if (cartItemsContainer) {
            cartItemsContainer.addEventListener("click", (event) => {
                const minusButton = event.target.closest("[data-cart-qty-minus]");
                const plusButton = event.target.closest("[data-cart-qty-plus]");
                const editButton = event.target.closest("[data-edit-cart-item]");
                const deleteButton = event.target.closest("[data-delete-cart-item]");

                if (minusButton) {
                    const dishId = Number(minusButton.dataset.cartQtyMinus);
                    const cartItem = cart.items.find((item) => Number(item.dish_id) === dishId);
                    if (cartItem) {
                        const nextQuantity = Math.max(0, Number(cartItem.quantity) - 1);
                        if (nextQuantity <= 0) {
                            promptCartItemRemoval(dishId, cartItem.note || "");
                        } else {
                            updateDishQuantity(dishId, nextQuantity, cartItem.note || "").catch(() => {});
                        }
                    }
                    return;
                }

                if (plusButton) {
                    const dishId = Number(plusButton.dataset.cartQtyPlus);
                    const cartItem = cart.items.find((item) => Number(item.dish_id) === dishId);
                    if (cartItem) {
                        updateDishQuantity(dishId, Number(cartItem.quantity) + 1, cartItem.note || "").catch(() => {});
                    }
                    return;
                }

                if (editButton) {
                    openDishModal(Number(editButton.dataset.editCartItem), "edit");
                    return;
                }

                if (deleteButton) {
                    const dishId = Number(deleteButton.dataset.deleteCartItem);
                    const cartItem = cart.items.find((item) => Number(item.dish_id) === dishId);
                    promptCartItemRemoval(dishId, cartItem ? cartItem.note || "" : "");
                }
            });
        }

        if (cartOrdersCta) {
            cartOrdersCta.addEventListener("click", () => {
                if (cartOrdersCta.disabled) {
                    return;
                }

                const orderUrl = cartOrdersCta.dataset.orderUrl;
                if (orderUrl) {
                    window.location.href = orderUrl;
                }
            });
        }

        if (cartConfirmModal) {
            const confirmAcceptButton = cartConfirmModal.querySelector("[data-cart-confirm-accept='true']");
            const confirmCancelButtons = Array.from(cartConfirmModal.querySelectorAll("[data-cart-confirm-cancel='true']"));

            confirmCancelButtons.forEach((button) => {
                button.addEventListener("click", () => {
                    pendingZeroQuantitySubmit = null;
                    closeZeroQuantityConfirm();
                });
            });

            if (confirmAcceptButton) {
                confirmAcceptButton.addEventListener("click", () => {
                    if (!pendingZeroQuantitySubmit) {
                        closeZeroQuantityConfirm();
                        return;
                    }

                    const { dishId, note } = pendingZeroQuantitySubmit;
                    pendingZeroQuantitySubmit = null;
                    closeZeroQuantityConfirm();
                    updateDishQuantity(dishId, 0, note || "").catch(() => {});
                    closeDishModal();
                });
            }
        }

        if (modal) {
            modal.addEventListener("click", (event) => {
                if (event.target.closest("[data-close-dish-modal='true']")) {
                    closeDishModal();
                }
            });

            const minusButton = modal.querySelector("[data-modal-qty-minus='true']");
            const plusButton = modal.querySelector("[data-modal-qty-plus='true']");
            const submitButton = modal.querySelector("[data-dish-modal-submit='true']");
            const noteField = modal.querySelector("[data-dish-modal-note='true']");

            if (minusButton) {
                minusButton.addEventListener("click", () => {
                    modalQuantity = Math.max(0, modalQuantity - 1);
                    updateModalSubmitLabel();
                });
            }

            if (plusButton) {
                plusButton.addEventListener("click", () => {
                    modalQuantity += 1;
                    updateModalSubmitLabel();
                });
            }

            if (submitButton) {
                submitButton.addEventListener("click", () => {
                    if (modalDishId == null) {
                        return;
                    }

                    const dish = dishById.get(Number(modalDishId));
                    if (!isDishAvailable(dish) || submitButton.disabled) {
                        return;
                    }

                    const note = noteField ? noteField.value : "";
                    if (modalQuantity <= 0) {
                        promptCartItemRemoval(modalDishId, note);
                        return;
                    }

                    const action = modalMode === "edit"
                        ? updateDishQuantity(modalDishId, modalQuantity, note)
                        : addDishToCart(modalDishId, modalQuantity, note);

                    action
                        .then(() => {
                            closeDishModal();
                        })
                        .catch(() => {});
                });
            }
        }

        document.addEventListener("keydown", (event) => {
            if (cartConfirmModal && !cartConfirmModal.hidden && event.key === "Escape") {
                pendingZeroQuantitySubmit = null;
                closeZeroQuantityConfirm();
                return;
            }

            if (reviewModal && !reviewModal.hidden && event.key === "Escape") {
                closeReviewModal();
                return;
            }

            if (event.key === "Escape" && modal && !modal.hidden) {
                closeDishModal();
            }
        });

        syncCategoryTabs();
        applyFilters();
        renderCart();
        syncCartCtaState();
    }

    function initAll() {
        document.querySelectorAll(ROOT_SELECTOR).forEach(initRestaurantDetail);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initAll);
    } else {
        initAll();
    }
})();
