(function () {
    function escapeText(value) {
        return value == null ? "" : String(value);
    }

    function buildNotificationItem(notification) {
        const link = document.createElement("a");
        const isUnread = !notification?.is_read;
        link.className = `site-header__notification-item${isUnread ? " is-unread" : ""}`;
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

    function ensureEmptyState(wrapper) {
        let empty = wrapper.querySelector(".site-header__notification-empty");
        if (empty) {
            empty.textContent = "Không có thông báo";
            return empty;
        }

        empty = document.createElement("div");
        empty.className = "site-header__notification-empty";
        empty.textContent = "Không có thông báo";
        wrapper.appendChild(empty);
        return empty;
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

    function updateUnreadSummary(value) {
        const nextValue = Math.max(0, Number(value) || 0);
        const unreadText = document.querySelector("[data-notification-unread-text]");
        if (unreadText) {
            unreadText.textContent = `${nextValue} chưa đọc`;
        }

        const markAllButton = document.querySelector("[data-mark-all-read='true']");
        if (markAllButton) {
            markAllButton.disabled = nextValue <= 0;
        }
    }

    function updateCount(value) {
        const nextValue = Math.max(0, Number(value) || 0);
        const badge = document.querySelector("[data-notification-count]");

        if (!badge) {
            if (nextValue > 0) {
                const button = document.querySelector(".site-header__notifications-button");
                if (button) {
                    const nextBadge = document.createElement("span");
                    nextBadge.className = "site-header__notification-badge";
                    nextBadge.dataset.notificationCount = "true";
                    nextBadge.textContent = String(nextValue);
                    button.appendChild(nextBadge);
                }
            }
            updateUnreadSummary(nextValue);
            return;
        }

        if (nextValue > 0) {
            badge.textContent = String(nextValue);
            badge.hidden = false;
        } else {
            badge.remove();
        }

        updateUnreadSummary(nextValue);
    }

    function shouldShowToast(notification) {
        return notification?.type !== "customer_order_confirmed";
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

        let list = notificationMenu.querySelector("[data-notification-list]");
        if (!list) {
            ensureEmptyState(notificationMenu);
        }

        let unreadCount = Number(document.querySelector("[data-notification-count]")?.textContent || 0);
        updateUnreadSummary(unreadCount);

        const socket = window.io({
            transports: ["websocket", "polling"],
            withCredentials: true,
        });

        socket.on("notification:new", (notification) => {
            if (!notification || !notification.notification_id) {
                return;
            }

            list = ensureNotificationList(notificationMenu);
            const item = buildNotificationItem(notification);
            list.prepend(item);

            if (!notification.is_read) {
                unreadCount += 1;
                updateCount(unreadCount);
            }

            if (shouldShowToast(notification) && window.AppToast && typeof window.AppToast.info === "function") {
                window.AppToast.info(notification.title || "Thông báo mới");
            }
        });

        document.addEventListener("click", (event) => {
            const markAllButton = event.target.closest("[data-mark-all-read='true']");
            if (markAllButton) {
                event.preventDefault();
                if (markAllButton.disabled) {
                    return;
                }

                fetch("/notifications/read-all", {
                    method: "POST",
                    headers: {
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    credentials: "same-origin",
                })
                    .then((response) => {
                        if (!response.ok) {
                            throw new Error("Failed to mark all notifications as read.");
                        }
                        return response.json();
                    })
                    .then(() => {
                        notificationMenu.querySelectorAll(".site-header__notification-item.is-unread").forEach((item) => {
                            item.classList.remove("is-unread");
                        });
                        unreadCount = 0;
                        updateCount(unreadCount);
                    })
                    .catch(() => {});

                return;
            }

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
            const wasUnread = link.classList.contains("is-unread");
            const markReadUrl = `/notifications/${notificationId}/read`;

            fetch(markReadUrl, {
                method: "POST",
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                },
                credentials: "same-origin",
            }).catch(() => {}).finally(() => {
                link.classList.remove("is-unread");
                if (wasUnread) {
                    unreadCount = Math.max(0, unreadCount - 1);
                    updateCount(unreadCount);
                }
                window.location.href = targetUrl;
            });
        });
    });
})();
