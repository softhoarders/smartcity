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
        const dropzone = document.getElementById("plate-doc-dropzone");
        const filenameEl = document.getElementById("plate-doc-filename");
        const titleEl = dropzone?.querySelector(".pw-file-dropzone-title");

        function setStatus(message, isError) {
            if (!statusEl) return;
            statusEl.textContent = message || "";
            statusEl.classList.toggle("text-danger", Boolean(isError));
            statusEl.classList.toggle("text-secondary", !isError && Boolean(message));
        }

        function clearFile() {
            if (fileInput) fileInput.value = "";
            dropzone?.classList.remove("has-file");
            if (filenameEl) {
                filenameEl.hidden = true;
                filenameEl.textContent = "";
            }
            if (titleEl) titleEl.textContent = "Drop your document here";
        }

        function validateAndShowFile(file) {
            if (!file) {
                clearFile();
                setStatus("");
                return false;
            }
            const ext = (file.name.split(".").pop() || "").toLowerCase();
            if (!ALLOWED.includes(ext)) {
                setStatus("Use a PDF or Word file (.pdf, .doc, .docx).", true);
                clearFile();
                return false;
            }
            if (file.size > MAX_BYTES) {
                setStatus("File must be 8 MB or smaller.", true);
                clearFile();
                return false;
            }
            dropzone?.classList.add("has-file");
            if (filenameEl) {
                filenameEl.hidden = false;
                filenameEl.textContent = file.name;
            }
            if (titleEl) titleEl.textContent = "Document ready";
            setStatus(`${file.name} ready to verify.`, false);
            return true;
        }

        fileInput?.addEventListener("change", () => {
            validateAndShowFile(fileInput.files?.[0]);
        });

        if (dropzone) {
            ["dragenter", "dragover"].forEach((evt) => {
                dropzone.addEventListener(evt, (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    dropzone.classList.add("is-dragover");
                });
            });

            ["dragleave", "drop"].forEach((evt) => {
                dropzone.addEventListener(evt, (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    dropzone.classList.remove("is-dragover");
                });
            });

            dropzone.addEventListener("drop", (e) => {
                const file = e.dataTransfer?.files?.[0];
                if (!file || !fileInput) return;
                const dt = new DataTransfer();
                dt.items.add(file);
                fileInput.files = dt.files;
                validateAndShowFile(file);
            });

            dropzone.addEventListener("keydown", (e) => {
                if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    fileInput?.click();
                }
            });
        }

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
