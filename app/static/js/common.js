(function () {
    const TOAST_POSITION = "top-right";
    const DEFAULT_HEADING = {
        success: "Thành công",
        error: "Lỗi",
        warning: "Cảnh báo",
        info: "Thông báo",
    };

    function normalizeType(type) {
        if (type === "danger") {
            return "error";
        }

        if (type === "message") {
            return "info";
        }

        return DEFAULT_HEADING[type] ? type : "info";
    }

    function canUseJqueryToast() {
        return Boolean(window.jQuery && typeof window.jQuery.toast === "function");
    }

    function buildToastOptions(type, message, options) {
        const normalizedType = normalizeType(type);
        const resolvedOptions = options || {};

        return {
            heading: resolvedOptions.heading || DEFAULT_HEADING[normalizedType],
            text: message || "",
            icon: normalizedType,
            position: resolvedOptions.position || TOAST_POSITION,
            showHideTransition: resolvedOptions.showHideTransition || "slide",
            allowToastClose: resolvedOptions.allowToastClose !== false,
            hideAfter: resolvedOptions.hideAfter === undefined ? 4000 : resolvedOptions.hideAfter,
            stack: resolvedOptions.stack === undefined ? 5 : resolvedOptions.stack,
            loader: resolvedOptions.loader !== false,
            loaderBg: resolvedOptions.loaderBg || "#f97316",
            textAlign: resolvedOptions.textAlign || "left",
            ...resolvedOptions,
            icon: normalizedType,
            position: resolvedOptions.position || TOAST_POSITION,
        };
    }

    function show(type, message, options) {
        const toastOptions = buildToastOptions(type, message, options);

        if (canUseJqueryToast()) {
            window.jQuery.toast(toastOptions);
            return;
        }

        window.alert(message || toastOptions.heading);
    }

    function success(message, options) {
        show("success", message, options);
    }

    function error(message, options) {
        show("error", message, options);
    }

    function warning(message, options) {
        show("warning", message, options);
    }

    function info(message, options) {
        show("info", message, options);
    }

    function showFlashedMessages() {
        const flashScript = document.getElementById("app-flash-messages");
        if (!flashScript) {
            return;
        }

        let flashedMessages = [];

        try {
            flashedMessages = JSON.parse(flashScript.textContent || "[]");
        } catch (error) {
            flashedMessages = [];
        }

        flashedMessages.forEach((item) => {
            if (!Array.isArray(item) || item.length < 2) {
                return;
            }

            const category = item[0];
            const message = item[1];
            show(category, message);
        });
    }

    function initScrollTopButton() {
        const scrollTopButton = document.querySelector("[data-scroll-top='true']");
        if (!scrollTopButton) {
            return;
        }

        const toggleVisibility = () => {
            const shouldShow = window.scrollY > 280;
            scrollTopButton.classList.toggle("is-visible", shouldShow);
        };

        scrollTopButton.addEventListener("click", () => {
            window.scrollTo({
                top: 0,
                behavior: "smooth",
            });
        });

        window.addEventListener("scroll", toggleVisibility, { passive: true });
        toggleVisibility();
    }

    window.AppToast = {
        show,
        success,
        error,
        warning,
        info,
    };

    window.showSuccessToast = success;
    window.showErrorToast = error;
    window.showWarningToast = warning;

    document.addEventListener("DOMContentLoaded", () => {
        showFlashedMessages();
        initScrollTopButton();
    });
})();
