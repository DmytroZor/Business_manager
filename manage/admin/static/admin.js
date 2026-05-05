(function () {
    function updateSelectedOrder(orderId) {
        const selectedInput = document.getElementById("selected-order-id");
        if (selectedInput) {
            selectedInput.value = orderId || "";
        }

        document.querySelectorAll("[data-order-link]").forEach((link) => {
            link.classList.toggle("is-active", (link.dataset.orderId || "") === String(orderId || ""));
        });
    }

    async function requestFragment(url, options) {
        const response = await fetch(url, {
            credentials: "same-origin",
            headers: {
                "HX-Request": "true",
                "X-Requested-With": "XMLHttpRequest",
            },
            ...options,
        });

        if (response.redirected) {
            window.location.href = response.url;
            return null;
        }

        return {
            html: await response.text(),
            trigger: response.headers.get("HX-Trigger"),
        };
    }

    function dispatchHxTrigger(triggerValue) {
        if (!triggerValue) {
            return;
        }
        document.body.dispatchEvent(new CustomEvent(triggerValue, { bubbles: true }));
    }

    async function refreshOrdersListWithFallback() {
        const filtersForm = document.getElementById("orders-filters");
        const ordersList = document.getElementById("orders-list");
        if (!filtersForm || !ordersList) {
            return;
        }

        if (window.htmx) {
            window.htmx.trigger(ordersList, "refresh");
            return;
        }

        const url = new URL(filtersForm.getAttribute("hx-get") || filtersForm.action, window.location.origin);
        const params = new URLSearchParams(new FormData(filtersForm));
        url.search = params.toString();

        const result = await requestFragment(url.toString(), { method: "GET" });
        if (result) {
            ordersList.innerHTML = result.html;
        }
    }

    document.body.addEventListener("refresh-orders-list", function () {
        void refreshOrdersListWithFallback();
    });

    document.addEventListener("submit", function (event) {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) {
            return;
        }

        if (!window.htmx && form.id === "orders-filters" && form.hasAttribute("hx-get")) {
            event.preventDefault();

            const url = new URL(form.getAttribute("hx-get") || form.action, window.location.origin);
            const params = new URLSearchParams(new FormData(form));
            url.search = params.toString();

            void requestFragment(url.toString(), { method: "GET" }).then((result) => {
                if (!result) {
                    return;
                }
                const targetSelector = form.getAttribute("hx-target");
                const target = targetSelector ? document.querySelector(targetSelector) : null;
                if (target) {
                    target.innerHTML = result.html;
                }
                window.history.replaceState({}, "", url.toString());
            });
            return;
        }

        if (!window.htmx && form.hasAttribute("hx-post")) {
            event.preventDefault();

            const targetSelector = form.getAttribute("hx-target");
            const target = targetSelector ? document.querySelector(targetSelector) : null;
            if (!target) {
                form.submit();
                return;
            }

            void requestFragment(form.getAttribute("hx-post") || form.action, {
                method: "POST",
                body: new FormData(form),
            }).then((result) => {
                if (!result) {
                    return;
                }
                target.innerHTML = result.html;
                dispatchHxTrigger(result.trigger);
            });
        }
    });

    document.addEventListener("click", function (event) {
        const orderLink = event.target.closest("[data-order-link]");
        if (orderLink) {
            updateSelectedOrder(orderLink.dataset.orderId || "");

            if (!window.htmx && orderLink.hasAttribute("hx-get")) {
                event.preventDefault();

                const targetSelector = orderLink.getAttribute("hx-target");
                const target = targetSelector ? document.querySelector(targetSelector) : null;
                if (!target) {
                    window.location.href = orderLink.href;
                    return;
                }

                void requestFragment(orderLink.getAttribute("hx-get"), {
                    method: "GET",
                }).then((result) => {
                    if (!result) {
                        return;
                    }
                    target.innerHTML = result.html;
                    window.history.replaceState({}, "", orderLink.href);
                });
            }
            return;
        }

        const addButton = event.target.closest("[data-add-item]");
        if (addButton) {
            const target = document.getElementById("phone-order-items");
            const template = document.getElementById("order-item-template");
            if (target && template) {
                target.insertAdjacentHTML("beforeend", template.innerHTML);
            }
            return;
        }

        const removeButton = event.target.closest("[data-remove-item]");
        if (removeButton) {
            const rows = document.querySelectorAll(".order-item-row");
            const row = removeButton.closest(".order-item-row");
            if (row && rows.length > 1) {
                row.remove();
            }
        }
    });
})();
