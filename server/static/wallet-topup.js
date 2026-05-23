(function () {
    const BRANDS = {
        visa: /^4/,
        mastercard: /^(5[1-5]|2[2-7])/,
        amex: /^3[47]/,
    };

    function detectBrand(number) {
        const digits = (number || "").replace(/\D/g, "");
        if (BRANDS.amex.test(digits)) return "amex";
        if (BRANDS.mastercard.test(digits)) return "mastercard";
        if (BRANDS.visa.test(digits)) return "visa";
        return "generic";
    }

    function formatCardNumber(value) {
        const digits = value.replace(/\D/g, "").slice(0, 16);
        return digits.replace(/(\d{4})(?=\d)/g, "$1 ").trim();
    }

    function formatExpiry(value) {
        const digits = value.replace(/\D/g, "").slice(0, 4);
        if (digits.length <= 2) return digits;
        return digits.slice(0, 2) + "/" + digits.slice(2);
    }

    function maskNumber(value) {
        const digits = value.replace(/\D/g, "");
        if (!digits) return "•••• •••• •••• ••••";
        const padded = (digits + "0000000000000000").slice(0, 16);
        const groups = padded.match(/.{1,4}/g) || [];
        return groups
            .map((g, i) => {
                if (i < groups.length - 1) return "••••";
                return g.padEnd(4, "•");
            })
            .join(" ");
    }

    function displayNumber(value) {
        const digits = value.replace(/\D/g, "");
        if (!digits) return "•••• •••• •••• ••••";
        const formatted = formatCardNumber(digits);
        const missing = 19 - formatted.length;
        return formatted + (missing > 0 ? " " + "•".repeat(Math.min(missing, 4)) : "");
    }

    document.addEventListener("DOMContentLoaded", () => {
        const form = document.getElementById("topup-form");
        const cardPreview = document.getElementById("pay-card");
        if (!form || !cardPreview) return;

        const numberInput = form.querySelector('[name="card_number"]');
        const nameInput = form.querySelector('[name="card_name"]');
        const expiryInput = form.querySelector('[name="card_expiry"]');
        const cvcInput = form.querySelector('[name="card_cvc"]');
        const leiInput = document.getElementById("lei-input");
        const previewNumber = document.getElementById("pay-card-number");
        const previewName = document.getElementById("pay-card-name");
        const previewExpiry = document.getElementById("pay-card-expiry");
        const previewBrand = document.getElementById("pay-card-brand");
        const creditsPreview = document.getElementById("credits-preview");
        const processing = document.getElementById("pay-processing");
        const quickAmounts = document.querySelectorAll("[data-quick-amount]");

        function updatePreview() {
            const digits = (numberInput?.value || "").replace(/\D/g, "");
            const brand = detectBrand(digits);
            cardPreview.dataset.brand = brand;
            if (previewNumber) {
                previewNumber.textContent = digits.length >= 12 ? maskNumber(digits) : displayNumber(digits);
            }
            if (previewName) {
                previewName.textContent = (nameInput?.value || "YOUR NAME").toUpperCase().slice(0, 26) || "YOUR NAME";
            }
            if (previewExpiry) {
                previewExpiry.textContent = expiryInput?.value || "MM/YY";
            }
            if (previewBrand) {
                previewBrand.textContent = brand === "generic" ? "CARD" : brand.toUpperCase();
            }
            cardPreview.classList.toggle("is-flipped", document.activeElement === cvcInput);
        }

        numberInput?.addEventListener("input", () => {
            numberInput.value = formatCardNumber(numberInput.value);
            updatePreview();
        });
        nameInput?.addEventListener("input", updatePreview);
        expiryInput?.addEventListener("input", () => {
            expiryInput.value = formatExpiry(expiryInput.value);
            updatePreview();
        });
        cvcInput?.addEventListener("input", () => {
            cvcInput.value = cvcInput.value.replace(/\D/g, "").slice(0, 4);
            updatePreview();
        });
        cvcInput?.addEventListener("focus", () => cardPreview.classList.add("is-flipped"));
        cvcInput?.addEventListener("blur", () => cardPreview.classList.remove("is-flipped"));

        if (leiInput && creditsPreview) {
            const syncCredits = () => {
                creditsPreview.textContent = String(Math.max(1, parseInt(leiInput.value, 10) || 0));
            };
            leiInput.addEventListener("input", syncCredits);
            syncCredits();
        }

        quickAmounts.forEach((btn) => {
            btn.addEventListener("click", () => {
                if (!leiInput) return;
                leiInput.value = btn.dataset.quickAmount || "50";
                leiInput.dispatchEvent(new Event("input"));
                leiInput.focus();
            });
        });

        form.addEventListener("submit", (event) => {
            if (form.dataset.confirmed === "true") return;
            event.preventDefault();
            if (!processing) {
                form.dataset.confirmed = "true";
                form.submit();
                return;
            }
            processing.hidden = false;
            processing.setAttribute("aria-hidden", "false");
            const steps = processing.querySelectorAll("[data-pay-step]");
            steps.forEach((step, index) => {
                step.classList.toggle("is-active", index === 0);
                step.classList.remove("is-done");
            });
            let stepIndex = 0;
            const advance = () => {
                if (stepIndex < steps.length) {
                    if (stepIndex > 0) steps[stepIndex - 1].classList.add("is-done");
                    steps[stepIndex]?.classList.add("is-active");
                    stepIndex += 1;
                }
            };
            advance();
            const timer = setInterval(() => {
                if (stepIndex >= steps.length) {
                    clearInterval(timer);
                    form.dataset.confirmed = "true";
                    form.submit();
                    return;
                }
                advance();
            }, 650);
        });

        updatePreview();
    });
})();
