(function () {
    const ALLOWED = ["pdf", "doc", "docx"];
    const MAX_BYTES = 8 * 1024 * 1024;

    document.addEventListener("DOMContentLoaded", () => {
        const form = document.getElementById("plate-upload-form");
        if (!form) return;

        const fileInput = form.querySelector('[name="registration_document"]');
        const plateInput = form.querySelector('[name="license_plate"]');
        const statusEl = document.getElementById("plate-upload-status");
        const submitBtn = form.querySelector('[type="submit"]');

        function setStatus(message, isError) {
            if (!statusEl) return;
            statusEl.textContent = message || "";
            statusEl.classList.toggle("text-danger", Boolean(isError));
            statusEl.classList.toggle("text-secondary", !isError && Boolean(message));
        }

        fileInput?.addEventListener("change", () => {
            const file = fileInput.files?.[0];
            if (!file) {
                setStatus("");
                return;
            }
            const ext = (file.name.split(".").pop() || "").toLowerCase();
            if (!ALLOWED.includes(ext)) {
                setStatus("Use a PDF or Word file (.pdf, .doc, .docx).", true);
                fileInput.value = "";
                return;
            }
            if (file.size > MAX_BYTES) {
                setStatus("File must be 8 MB or smaller.", true);
                fileInput.value = "";
                return;
            }
            setStatus(`${file.name} ready to verify.`, false);
        });

        form.addEventListener("submit", () => {
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.dataset.originalLabel = submitBtn.textContent;
                submitBtn.textContent = "Verifying document…";
            }
            setStatus("Sending to verification — this may take up to a minute.", false);
        });

        plateInput?.addEventListener("input", () => {
            plateInput.value = plateInput.value.toUpperCase().replace(/[^A-Z0-9]/g, "");
        });
    });
})();
