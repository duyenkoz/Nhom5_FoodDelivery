(function () {
    function escapeText(value) {
        return value == null ? "" : String(value);
    }

    function buildNotificationItem(notification) {
        const link = document.createElement("a");
        link.className = "site-header__notification-item is-unread";
        link.href = notification.link || "#";
        link.dataset.notificationLink = "true";
        link.dataset.notificationId = notification.notification_id;

        const title = document.createElement("strong");
        title.textContent = escapeText(notification.title || "Thông báo");

        const message = document.createElement("span");
        message.textContent = escapeText(notification.message || "");

        const time = document.createElement("small");
        time.textContent = escapeText(notification.created_at_text || "");

        link.appendChild(title);
        link.appendChild(message);
        link.appendChild(time);
        return link;
    }

    function ensureNotificationList(wrapper) {
        let list = wrapper.querySelector("[data-notification-list]");
        if (list) {
            return list;
        }

        const empty = wrapper.querySelector(".site-header__notification-empty");
        if (empty) {
            empty.remove();
        }

        list = document.createElement("div");
        list.className = "site-header__notification-list";
        list.dataset.notificationList = "true";
        wrapper.appendChild(list);
        return list;
    }

    function updateCount(value) {
        const badge = document.querySelector("[data-notification-count]");
        if (!badge) {
            if (Number(value) <= 0) {
                return;
            }
            const button = document.querySelector(".site-header__notifications-button");
            if (!button) {
                return;
            }
            const nextBadge = document.createElement("span");
            nextBadge.className = "site-header__notification-badge";
            nextBadge.dataset.notificationCount = "true";
            nextBadge.textContent = String(value);
            button.appendChild(nextBadge);
            return;
        }

        const nextValue = Math.max(0, Number(value) || 0);
        if (nextValue > 0) {
            badge.textContent = String(nextValue);
            badge.hidden = false;
        } else {
            badge.remove();
        }
    }

    document.addEventListener("DOMContentLoaded", () => {
        const userId = document.body.dataset.appUserId;
        if (!userId || !window.io) {
            return;
        }

        const notificationMenu = document.querySelector(".site-header__notification-menu");
        if (!notificationMenu) {
            return;
        }

        const list = ensureNotificationList(notificationMenu);
        let unreadCount = Number(document.querySelector("[data-notification-count]")?.textContent || 0);
        const socket = window.io({
            transports: ["websocket", "polling"],
            withCredentials: true,
        });

        socket.on("notification:new", (notification) => {
            if (!notification || !notification.notification_id) {
                return;
            }

            const item = buildNotificationItem(notification);
            list.prepend(item);
            unreadCount += 1;
            updateCount(unreadCount);

            if (window.AppToast && typeof window.AppToast.info === "function") {
                window.AppToast.info(notification.title || "Thông báo mới");
            }
        });

        document.addEventListener("click", (event) => {
            const link = event.target.closest("[data-notification-link='true']");
            if (!link) {
                return;
            }

            const notificationId = link.dataset.notificationId;
            if (!notificationId) {
                return;
            }

            event.preventDefault();
            const targetUrl = link.href;
            const markReadUrl = `/notifications/${notificationId}/read`;

            fetch(markReadUrl, {
                method: "POST",
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                },
                credentials: "same-origin",
            }).catch(() => {}).finally(() => {
                link.classList.remove("is-unread");
                unreadCount = Math.max(0, unreadCount - 1);
                updateCount(unreadCount);
                window.location.href = targetUrl;
            });
        });
    });
})();
