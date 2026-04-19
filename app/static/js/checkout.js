(function () {
    const dataEl = document.getElementById("checkout-page-data");
    const pageData = dataEl ? JSON.parse(dataEl.textContent || "{}") : {};

    const voucherModal = document.getElementById("voucherModal");
    const openVoucherModalBtn = document.getElementById("openVoucherModalBtn");
    const voucherChipText = document.getElementById("voucherChipText");
    const voucherId = document.getElementById("voucher_id");
    const voucherCodeHidden = document.getElementById("voucher_code_hidden");
    const voucherModalMessage = document.getElementById("voucherModalMessage");
    const voucherList = document.getElementById("voucherList");
    const saveVoucherSelectionBtn = document.getElementById("saveVoucherSelectionBtn");
    const checkoutItemsList = document.getElementById("checkoutItemsList");
    const checkoutItemsJson = document.getElementById("checkout_items_json");
    const checkoutForm = document.getElementById("checkoutForm");
    const checkoutEmptyModal = document.getElementById("checkoutEmptyModal");
    const checkoutEmptyModalOk = document.getElementById("checkoutEmptyModalOk");
    const subtotalValue = document.getElementById("subtotalValue");
    const deliveryFeeValue = document.getElementById("deliveryFeeValue");
    const discountValueEl = document.getElementById("discountValue");
    const totalValue = document.getElementById("totalValue");
    const summary = document.querySelector(".checkout-summary");
    const itemEditModal = document.getElementById("itemEditModal");
    const itemEditImage = document.getElementById("itemEditImage");
    const itemEditName = document.getElementById("itemEditName");
    const itemEditPrice = document.getElementById("itemEditPrice");
    const itemEditQuantity = document.getElementById("itemEditQuantity");
    const itemEditNote = document.getElementById("itemEditNote");
    const itemEditSubtitle = document.getElementById("itemEditModalSubtitle");
    const saveItemEditBtn = document.getElementById("saveItemEditBtn");
    const deliveryAddressInput = document.getElementById("delivery_address");
    const deliveryFeeTip = document.querySelector("[data-delivery-fee-tip]");
    const voucherSummaryLabel = document.querySelector("[data-voucher-summary-label]");
    const checkoutQuoteUrl = pageData.checkout_quote_url || "";
    const restaurantDetailUrl = pageData.restaurant_detail_url || "";
    const checkoutCartUpdateUrlTemplate = pageData.checkout_cart_update_url_template || "";

    if (!checkoutForm || !checkoutItemsJson || !summary) return;

    let checkoutItems = JSON.parse(checkoutItemsJson.value || "[]").map(normalizeItem);
    let selectedVoucher = {
        code: pageData.voucher_code || "",
        id: pageData.voucher_id || "",
        text: pageData.voucher_text || "Khuyến mãi",
        discountValue: Number(pageData.discount_value || 0),
    };
    let editingItemKey = null;
    let emptyCartPending = false;
    let quoteTimer = null;

    function formatMoney(value) {
        return new Intl.NumberFormat("vi-VN").format(Math.max(0, Number(value) || 0)) + "đ";
    }

    function formatSummaryMoney(value) {
        return new Intl.NumberFormat("vi-VN").format(Math.max(0, Number(value) || 0)).replace(/,/g, ".");
    }

    function safeText(value) {
        return (value == null ? "" : String(value)).trim();
    }

    function resolveImageUrl(imageValue) {
        const value = safeText(imageValue);
        if (!value) {
            return "";
        }
        if (/^(https?:)?\/\//.test(value) || value.startsWith("/")) {
            return value;
        }
        return `/static/${value.replace(/^\/static\//, "")}`;
    }

    function serializeItem(item) {
        const { __key, ...rest } = item;
        return rest;
    }

    function normalizeItem(item, index) {
        const quantity = Math.max(1, Number(item.quantity) || 1);
        const price = Math.max(0, Number(item.price) || 0);
        const dishId = Number(item.dish_id || item.dishId || 0) || item.dish_id || item.dishId || index;
        const imagePath = safeText(item.image_path || item.image_url);
        return {
            ...item,
            __key: item.__key || String(dishId),
            dish_id: dishId,
            quantity,
            price,
            line_total: price * quantity,
            note: safeText(item.note),
            image_path: imagePath,
            image_url: resolveImageUrl(item.image_url || imagePath),
        };
    }

    function getCartUpdateUrl(dishId) {
        if (!checkoutCartUpdateUrlTemplate) {
            return "";
        }
        return checkoutCartUpdateUrlTemplate.replace(/0\/?$/, `${dishId}`);
    }

    function setEmptyCartModalOpen(isOpen) {
        if (!checkoutEmptyModal) return;
        checkoutEmptyModal.classList.toggle("is-open", Boolean(isOpen));
        checkoutEmptyModal.hidden = !isOpen;
        checkoutEmptyModal.setAttribute("aria-hidden", isOpen ? "false" : "true");
        document.body.classList.toggle("is-modal-open", Boolean(isOpen));
    }

    function openEmptyCartModal() {
        emptyCartPending = true;
        setEmptyCartModalOpen(true);
    }

    function closeEmptyCartModal() {
        emptyCartPending = false;
        setEmptyCartModalOpen(false);
    }

    function redirectToRestaurantDetail() {
        if (!restaurantDetailUrl) return;
        const target = new URL(restaurantDetailUrl, window.location.origin);
        target.searchParams.set("cart_cleared", "1");
        window.location.replace(target.toString());
    }

    function refreshTotals() {
        const subtotal = checkoutItems.reduce((sum, item) => sum + (Number(item.line_total) || 0), 0);
        const deliveryFee = Number(summary.dataset.deliveryFee || 0);
        const discountAmount = Number(selectedVoucher.discountValue || 0);
        subtotalValue.textContent = formatMoney(subtotal);
        deliveryFeeValue.textContent = formatMoney(deliveryFee);
        discountValueEl.textContent = discountAmount > 0 ? `-${formatMoney(discountAmount)}` : "0đ";
        totalValue.textContent = formatMoney(subtotal + deliveryFee - discountAmount);
        summary.dataset.subtotal = String(subtotal);
        checkoutItemsJson.value = JSON.stringify(checkoutItems.map(serializeItem));
    }

    function renderEmptyCheckoutState() {
        if (!checkoutItemsList) return;
        checkoutItemsList.innerHTML = '<div class="checkout-empty-state">Giỏ hàng đang trống. Hãy quay lại menu nhà hàng để chọn thêm món.</div>';
    }

    function persistItems() {
        checkoutItemsJson.value = JSON.stringify(checkoutItems.map(serializeItem));
    }

    function updateVoucherChip() {
        voucherChipText.textContent = selectedVoucher.code ? "Đã áp dụng 1 mã KM ......" : "Khuyến mãi ......";
        voucherCodeHidden.value = selectedVoucher.code || "";
        voucherId.value = selectedVoucher.id || "";
    }

    function updateVoucherSummaryLabel() {
        if (!voucherSummaryLabel) return;
        if (!selectedVoucher.code) {
            voucherSummaryLabel.textContent = "Giảm voucher";
            return;
        }
        const discountAmount = Number(selectedVoucher.discountValue || 0);
        voucherSummaryLabel.textContent = `[${selectedVoucher.code}] - Giảm ${formatSummaryMoney(discountAmount)}đ`;
    }

    function closeVoucherModal() {
        if (!voucherModal) return;
        voucherModal.classList.remove("is-open");
        voucherModal.setAttribute("aria-hidden", "true");
    }

    function closeItemModal() {
        if (!itemEditModal) return;
        itemEditModal.classList.remove("is-open");
        itemEditModal.setAttribute("aria-hidden", "true");
        editingItemKey = null;
    }

    function getItemRowByKey(key) {
        if (!checkoutItemsList) return null;
        return checkoutItemsList.querySelector(`[data-item-key="${String(key)}"]`);
    }

    async function updateCartItemOnServer(dishId, quantity, note) {
        const url = getCartUpdateUrl(dishId);
        if (!url) {
            throw new Error("Không tìm thấy đường dẫn cập nhật giỏ hàng.");
        }
        const result = await fetchJson(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                quantity: quantity,
                note: note,
            }),
        });
        if (!result.response.ok || !result.data || !result.data.ok) {
            throw new Error((result.data && result.data.message) || "Không thể cập nhật giỏ hàng.");
        }
        return result.data.cart || { items: [], total_amount: 0, total_amount_text: formatMoney(0), is_empty: true };
    }

    function applyCartState(nextCart) {
        const nextItems = Array.isArray(nextCart && nextCart.items) ? nextCart.items.map(normalizeItem) : [];
        checkoutItems = nextItems;
        summary.dataset.subtotal = String(nextItems.reduce((sum, item) => sum + (Number(item.line_total) || 0), 0));
        checkoutItemsJson.value = JSON.stringify(nextItems.map(serializeItem));
        if (!nextItems.length) {
            renderEmptyCheckoutState();
        }
    }

    function updateRowFromItem(row, item) {
        const qtyEl = row.querySelector(".checkout-item__qty");
        const priceEl = row.querySelector(".checkout-item__price");
        const noteEl = row.querySelector(".checkout-item__note");
        const metaEl = row.querySelector(".checkout-item__meta");
        const editBtn = row.querySelector("[data-edit-item]");

        if (qtyEl) qtyEl.textContent = `${item.quantity}x`;
        if (priceEl) priceEl.textContent = formatMoney(item.line_total || 0);

        if (metaEl) {
            if (item.note) {
                let targetNoteEl = noteEl;
                if (!targetNoteEl) {
                    targetNoteEl = document.createElement("small");
                    targetNoteEl.className = "checkout-item__note";
                    if (editBtn) {
                        metaEl.insertBefore(targetNoteEl, editBtn);
                    } else {
                        metaEl.appendChild(targetNoteEl);
                    }
                }
                targetNoteEl.textContent = item.note;
            } else if (noteEl) {
                noteEl.remove();
            }
        }
    }

    function openItemModal(item) {
        if (!itemEditModal) return;
        editingItemKey = item.__key;
        itemEditName.textContent = item.name || "Món ăn";
        itemEditPrice.textContent = formatMoney(item.price || 0);
        itemEditQuantity.value = String(item.quantity || 1);
        itemEditNote.value = item.note || "";
        itemEditSubtitle.textContent = `Cập nhật số lượng và ghi chú cho ${item.name || "món ăn"} này.`;
        if (itemEditImage) {
            const imageSrc = resolveImageUrl(item.image_url || item.image_path);
            if (imageSrc) {
                itemEditImage.src = imageSrc;
                itemEditImage.alt = item.name || "Món ăn";
                itemEditImage.style.display = "";
            } else {
                itemEditImage.removeAttribute("src");
                itemEditImage.alt = "";
                itemEditImage.style.display = "none";
            }
        }
        itemEditModal.classList.add("is-open");
        itemEditModal.setAttribute("aria-hidden", "false");
        setTimeout(() => itemEditQuantity?.focus(), 0);
    }

    async function saveItemEdit() {
        if (editingItemKey == null) return;
        const item = checkoutItems.find((entry) => entry.__key === editingItemKey);
        if (!item) return;
        const quantity = Math.max(1, Number(itemEditQuantity.value) || 1);
        const note = safeText(itemEditNote.value);
        const row = getItemRowByKey(item.__key);
        try {
            const cart = await updateCartItemOnServer(item.dish_id, quantity, note);
            applyCartState(cart);
            if (row) {
                const nextItem = checkoutItems.find((entry) => String(entry.__key) === String(item.__key)) || {
                    ...item,
                    quantity,
                    note,
                    line_total: quantity * (Number(item.price) || 0),
                };
                updateRowFromItem(row, nextItem);
            }
            refreshTotals();
            syncCheckoutPayload();
            queueQuoteRefresh();
            closeItemModal();
        } catch (error) {
            voucherModalMessage.textContent = error.message || "Không thể cập nhật giỏ hàng.";
            voucherModalMessage.classList.add("is-error");
        }
    }

    async function syncCheckoutPayload() {
        await fetch(pageData.checkout_payload_url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                restaurant_id: pageData.restaurant_id || "",
                items: checkoutItems.map(serializeItem),
                delivery_fee: summary.dataset.deliveryFee || 0,
                shipping_fee: summary.dataset.shippingFee || 0,
                platform_fee: summary.dataset.platformFee || 0,
                raw_delivery_fee: summary.dataset.rawDeliveryFee || 0,
                note: document.getElementById("note")?.value || "",
            }),
        });
    }

    async function refreshQuote() {
        if (!checkoutQuoteUrl) return;

        await syncCheckoutPayload();
        const formData = new FormData(checkoutForm);
        try {
            const response = await fetch(checkoutQuoteUrl, {
                method: "POST",
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                    Accept: "application/json",
                },
                body: new URLSearchParams(formData),
            });
            const data = await response.json();
            if (!response.ok || !data || !data.ok) {
                return;
            }

            summary.dataset.deliveryFee = String(data.delivery_fee || 0);
            summary.dataset.shippingFee = String(data.shipping_fee || 0);
            summary.dataset.platformFee = String(data.platform_fee || 0);
            summary.dataset.rawDeliveryFee = String(data.raw_delivery_fee || 0);
            summary.dataset.distanceText = data.distance_text || "";
            summary.dataset.distanceKm = data.distance_km == null ? "" : String(data.distance_km);
        selectedVoucher.discountValue = data.discount_value !== undefined
                ? Number(data.discount_value || 0)
                : Number(selectedVoucher.discountValue || 0);
            if (data.voucher_id !== undefined) {
                selectedVoucher.id = data.voucher_id ? String(data.voucher_id) : "";
            }
            if (deliveryFeeTip) {
                deliveryFeeTip.title = `Phí ship: ${formatMoney(data.shipping_fee || 0)} | Phí sàn: ${formatMoney(data.platform_fee || 0)} | Khoảng cách: ${data.distance_text || "N/A"}`;
            }
            updateVoucherSummaryLabel();
            refreshTotals();
            await syncCheckoutPayload();
        } catch (error) {
            return;
        }
    }

    function queueQuoteRefresh() {
        if (quoteTimer) {
            window.clearTimeout(quoteTimer);
        }
        quoteTimer = window.setTimeout(() => {
            refreshQuote();
        }, 300);
    }

    async function fetchJson(url, options) {
        const response = await fetch(url, options);
        const contentType = response.headers.get("content-type") || "";
        const bodyText = await response.text();
        let data = null;

        if (contentType.includes("application/json")) {
            try {
                data = JSON.parse(bodyText);
            } catch (error) {
                data = null;
            }
        }

        return { response, data, bodyText };
    }

    async function loadVouchers() {
        const restaurantId = pageData.restaurant_id || "";
        voucherList.innerHTML = '<div class="voucher-empty">Đang tải mã khuyến mãi...</div>';
        try {
            const result = await fetchJson(`${pageData.checkout_vouchers_url}?restaurant_id=${encodeURIComponent(restaurantId)}`);
            const response = result.response;
            const data = result.data;
            if (!response.ok || !data.ok) {
                throw new Error((data && data.message) || "Không tải được mã khuyến mãi.");
            }
            const vouchers = data.vouchers || [];
            if (!vouchers.length) {
                voucherList.innerHTML = '<div class="voucher-empty">Chưa có mã khuyến mãi phù hợp.</div>';
                return;
            }
            voucherList.innerHTML = vouchers.map((voucher) => `
                <label class="voucher-card">
                    <input type="radio" name="voucher_pick" value="${voucher.voucher_code}" data-voucher-code="${voucher.voucher_code}" data-voucher-id="${voucher.voucher_id}">
                    <div class="voucher-card__content">
                        <strong>${voucher.voucher_code}</strong>
                        <span>${voucher.discount_text || ""}</span>
                    </div>
                </label>
            `).join("");
            voucherList.querySelectorAll("input[data-voucher-code]").forEach((radio) => {
                radio.addEventListener("change", () => {
                    selectedVoucher = {
                        code: radio.dataset.voucherCode || "",
                        id: radio.dataset.voucherId || "",
                        discountValue: 0,
                    };
                    voucherModalMessage.textContent = `Đã chọn mã ${selectedVoucher.code}.`;
                    voucherModalMessage.classList.remove("is-error");
                });
            });
            if (selectedVoucher.code) {
                voucherList.querySelectorAll("input[data-voucher-code]").forEach((radio) => {
                    if ((radio.dataset.voucherCode || "") === selectedVoucher.code) {
                        radio.checked = true;
                    }
                });
            }
        } catch (error) {
            voucherList.innerHTML = '<div class="voucher-empty">Không tải được mã khuyến mãi.</div>';
            voucherModalMessage.textContent = error.message || "Không tải được mã khuyến mãi.";
            voucherModalMessage.classList.add("is-error");
        }
    }

    async function openVoucherModal() {
        if (!voucherModal) return;
        await loadVouchers();
        voucherModal.classList.add("is-open");
        voucherModal.setAttribute("aria-hidden", "false");
    }

    openVoucherModalBtn?.addEventListener("click", openVoucherModal);
    document.querySelectorAll("[data-close-voucher-modal]").forEach((btn) => btn.addEventListener("click", closeVoucherModal));
    document.querySelectorAll("[data-close-item-modal]").forEach((btn) => btn.addEventListener("click", closeItemModal));

    saveVoucherSelectionBtn?.addEventListener("click", async () => {
        if (!selectedVoucher.code) {
            voucherModalMessage.textContent = "Vui lòng chọn một mã có sẵn.";
            voucherModalMessage.classList.add("is-error");
            return;
        }

        const payload = new URLSearchParams();
        payload.append("voucher_code", selectedVoucher.code);
        payload.append("restaurant_id", pageData.restaurant_id || "");

        try {
            const result = await fetchJson(pageData.checkout_voucher_url, {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8" },
                body: payload.toString(),
            });
            const response = result.response;
            const data = result.data;
            if (!response.ok || !data || !data.ok) {
                throw new Error((data && data.message) || "Mã voucher không hợp lệ.");
            }
            selectedVoucher.discountValue = Number(data.discount_value || 0);
            selectedVoucher.id = data.voucher_id || selectedVoucher.id || "";
            voucherModalMessage.textContent = data.message || `Đã áp dụng mã ${selectedVoucher.code}.`;
            voucherModalMessage.classList.remove("is-error");
            updateVoucherChip();
            updateVoucherSummaryLabel();
            refreshTotals();
            queueQuoteRefresh();
            closeVoucherModal();
        } catch (error) {
            voucherModalMessage.textContent = error.message || "Mã voucher không hợp lệ.";
            voucherModalMessage.classList.add("is-error");
        }
    });
    saveItemEditBtn?.addEventListener("click", saveItemEdit);

    checkoutItemsList?.addEventListener("click", (event) => {
        const editBtn = event.target.closest("[data-edit-item]");
        if (editBtn) {
            const row = editBtn.closest("[data-item-key]");
            if (!row) return;
            const item = checkoutItems.find((entry) => entry.__key === row.dataset.itemKey);
            if (item) {
                openItemModal(item);
            }
            return;
        }

        const removeBtn = event.target.closest("[data-remove-item]");
        if (!removeBtn) return;
        const row = removeBtn.closest("[data-item-key]");
        if (!row) return;
        const itemKey = row.dataset.itemKey;
        const item = checkoutItems.find((entry) => String(entry.__key) === String(itemKey));
        if (!item) return;
        updateCartItemOnServer(item.dish_id, 0, item.note || "")
            .then((cart) => {
                applyCartState(cart);
                if (row.parentNode) {
                    row.remove();
                }
                refreshTotals();
                syncCheckoutPayload();
                queueQuoteRefresh();
                if (!Array.isArray(cart.items) || !cart.items.length || cart.is_empty) {
                    openEmptyCartModal();
                }
            })
            .catch((error) => {
                voucherModalMessage.textContent = error.message || "Không thể xoá món khỏi giỏ hàng.";
                voucherModalMessage.classList.add("is-error");
            });
    });

    checkoutEmptyModalOk?.addEventListener("click", redirectToRestaurantDetail);

    checkoutForm?.addEventListener("submit", async (event) => {
        event.preventDefault();
        await syncCheckoutPayload();
        const formData = new FormData(checkoutForm);
        const paymentMethod = (formData.get("payment_method") || "cash").toString();
        try {
            const response = await fetch(checkoutForm.action, {
                method: "POST",
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json",
                },
                body: new URLSearchParams(formData),
            });
            const data = await response.json();
            if (!response.ok || !data || !data.success) {
                throw new Error((data && data.message) || "Không thể xử lý đơn hàng.");
            }

            if (paymentMethod === "momo") {
                window.location.href = data.momo_url || data.redirect_url || pageData.checkout_momo_url || "/checkout/momo";
                return;
            }

            window.location.href = data.redirect_url || "/checkout";
        } catch (error) {
            checkoutForm.submit();
        }
    });

    deliveryAddressInput?.addEventListener("input", queueQuoteRefresh);
    deliveryAddressInput?.addEventListener("change", queueQuoteRefresh);
    checkoutForm?.querySelectorAll("input, textarea, select").forEach((field) => {
        if (field === deliveryAddressInput) return;
        if (field.name === "voucher_code" || field.name === "voucher_id" || field.name === "payment_method") {
            field.addEventListener("change", queueQuoteRefresh);
        }
    });

    updateVoucherChip();
    updateVoucherSummaryLabel();
    refreshTotals();
    syncCheckoutPayload();
    queueQuoteRefresh();
    if (!checkoutItems.length) {
        renderEmptyCheckoutState();
    }
})();
