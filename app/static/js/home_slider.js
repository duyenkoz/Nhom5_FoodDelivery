(function () {
    function initSlider(track) {
        let isPointerDown = false;
        let startX = 0;
        let startScrollLeft = 0;
        let moved = false;
        let pendingLinkHref = "";

        function isInteractiveTarget(target) {
            return Boolean(target.closest("button, input, select, textarea, label"));
        }

        track.addEventListener("pointerdown", function (event) {
            if (event.pointerType === "mouse" && event.button !== 0) {
                return;
            }

            if (isInteractiveTarget(event.target)) {
                return;
            }

            isPointerDown = true;
            moved = false;
            startX = event.clientX;
            startScrollLeft = track.scrollLeft;
            pendingLinkHref = "";
            const link = event.target.closest("a[href]");
            if (link) {
                pendingLinkHref = link.href || "";
            }
            track.classList.add("is-dragging");
            track.setPointerCapture(event.pointerId);
        });

        track.addEventListener("pointermove", function (event) {
            if (!isPointerDown) {
                return;
            }

            const deltaX = event.clientX - startX;
            if (Math.abs(deltaX) > 4) {
                moved = true;
            }

            track.scrollLeft = startScrollLeft - deltaX;
        });

        function stopDragging(event) {
            if (!isPointerDown) {
                return;
            }

            const shouldFollowLink = !moved && pendingLinkHref;
            isPointerDown = false;
            track.classList.remove("is-dragging");

            if (event && typeof event.pointerId !== "undefined") {
                try {
                    track.releasePointerCapture(event.pointerId);
                } catch (error) {
                    // Ignore release errors when the pointer capture is already cleared.
                }
            }

            if (shouldFollowLink) {
                window.location.href = pendingLinkHref;
            }

            pendingLinkHref = "";
            moved = false;
        }

        track.addEventListener("pointerup", stopDragging);
        track.addEventListener("pointercancel", stopDragging);
        track.addEventListener("lostpointercapture", stopDragging);

        track.addEventListener("click", function (event) {
            if (!moved) {
                return;
            }

            event.preventDefault();
            event.stopPropagation();
            moved = false;
        }, true);
    }

    function initAll() {
        document.querySelectorAll("[data-slider-track='true']").forEach(initSlider);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initAll);
    } else {
        initAll();
    }
})();
