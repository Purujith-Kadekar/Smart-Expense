import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import api from "../api/client.js";

// Liquid Glass Upload page.
//
// Logic preserved bit-for-bit:
//   - category select required before dropzone activates
//   - POST /api/upload-url for presigned PUT URL
//   - PUT file bytes directly to S3
//   - POST /api/expenses/trigger-ocr to invoke Lambda OCR
//   - status state machine: idle | uploading | success | error
//   - all error messages preserved verbatim from the original

const CATEGORIES = [
  { value: "", label: "Select a category…" },
  { value: "college", label: "College" },
  { value: "mess", label: "Mess" },
  { value: "event", label: "Event" },
  { value: "other", label: "Other" },
];

const CATEGORY_META = {
  college: { color: "blue", emoji: "🎓" },
  mess: { color: "amber", emoji: "🍽" },
  event: { color: "purple", emoji: "🎉" },
  other: { color: "slate", emoji: "📦" },
};

export default function Upload() {
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("idle"); // idle | uploading | success | error
  const [message, setMessage] = useState("");
  const [s3Key, setS3Key] = useState("");

  // onDrop callback is identical to the original — the API calls and
  // status transitions have not been changed at all.
  const onDrop = useCallback(
    async (acceptedFiles) => {
      if (!category) {
        setStatus("error");
        setMessage("Pick a category before uploading.");
        return;
      }
      if (acceptedFiles.length === 0) return;
      const file = acceptedFiles[0];
      setStatus("uploading");
      setMessage("");
      setS3Key("");

      try {
        // 1. Ask Flask for a presigned PUT URL.
        const { data } = await api.post("/upload-url", {
          filename: file.name,
          category,
        });
        const { upload_url, s3_key } = data;

        // 2. PUT the file directly to S3.
        const response = await fetch(upload_url, {
          method: "PUT",
          body: file,
          headers: { "Content-Type": file.type || "image/jpeg" },
        });
        if (!response.ok) {
          throw new Error(
            `S3 PUT failed: ${response.status} ${response.statusText}`
          );
        }

        setS3Key(s3_key);

        // 3. Trigger OCR processing.
        setMessage("Upload complete. Running OCR on the receipt...");
        try {
          const ocrResp = await api.post("/expenses/trigger-ocr", { s3_key });
          const ocrData = ocrResp.data || {};
          if (ocrData.triggered && ocrData.expense) {
            const e = ocrData.expense;
            setStatus("success");
            setMessage(
              `Receipt processed — vendor: ${e.vendor || "Unknown"}, ` +
              `amount: ₹${Number(e.amount || 0).toLocaleString()}, ` +
              `date: ${e.date || "—"}. Open the Dashboard to see it.`
            );
          } else {
            setStatus("success");
            setMessage(
              "Upload complete. The receipt is being processed. " +
                "Refresh the Dashboard in ~10–20 seconds to see the extracted record."
            );
          }
        } catch (ocrErr) {
          console.warn("OCR trigger failed:", ocrErr);
          setStatus("success");
          setMessage(
            "Upload complete, but OCR processing may take a moment. " +
              "Refresh the Dashboard in ~10–20 seconds to see the extracted record."
          );
        }
      } catch (err) {
        console.error(err);
        setStatus("error");
        setMessage(
          err?.response?.data?.error || err?.message || "Upload failed."
        );
      }
    },
    [category]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "image/*": [".jpg", ".jpeg", ".png", ".heic"] },
    multiple: false,
    disabled: !category || status === "uploading",
  });

  // Compute display state for the dropzone copy + icon.
  const disabled = !category || status === "uploading";
  const headingText = isDragActive
    ? "Drop the file here…"
    : !category
    ? "Pick a category above to enable upload"
    : "Drag & drop a receipt photo here";
  const subText = "JPG, JPEG, PNG, HEIC — single file only";

  return (
    <div className="space-y-6 animate-fade-in max-w-3xl">
      {/* ───────── Header ───────── */}
      <div>
        <p className="eyebrow mb-1.5">Upload</p>
        <h2 className="text-2xl sm:text-3xl font-bold text-ink-900 tracking-tight">
          Upload a receipt
        </h2>
        <p className="text-sm text-ink-500 mt-1.5 leading-relaxed max-w-2xl">
          Pick a category, then drop a receipt photo. It will be uploaded to
          S3 and processed by OCR automatically — vendor and total are
          extracted without any manual entry.
        </p>
      </div>

      {/* ───────── Category selector ───────── */}
      <div>
        <label
          htmlFor="category"
          className="block text-sm font-medium text-ink-700 mb-1.5"
        >
          Category <span className="text-rose-500">*</span>
        </label>
        <div className="flex flex-wrap items-center gap-2">
          {/* Visual category — radio-like cards */}
          {CATEGORIES.filter((c) => c.value).map((c) => {
            const meta = CATEGORY_META[c.value] || CATEGORY_META.other;
            const isActive = category === c.value;
            return (
              <button
                key={c.value}
                type="button"
                onClick={() => setCategory(c.value)}
                className={`relative inline-flex items-center gap-2 px-3.5 py-2 rounded-xl text-sm font-medium transition-all duration-200 focus-ring
                  ${
                    isActive
                      ? "glass-tint text-brand-700 shadow-soft-sm"
                      : "glass-subtle text-ink-600 hover:text-ink-900 hover:bg-white/70"
                  }`}
              >
                <span aria-hidden="true" className="text-base">{meta.emoji}</span>
                <span>{c.label}</span>
                {isActive && (
                  <span className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-brand-600 ring-2 ring-white" />
                )}
              </button>
            );
          })}
        </div>
        {/* Hidden native select for screen readers / form autofill */}
        <select
          id="category"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="sr-only"
          aria-hidden="true"
          tabIndex={-1}
        >
          {CATEGORIES.map((c) => (
            <option key={c.value} value={c.value} disabled={!c.value}>
              {c.label}
            </option>
          ))}
        </select>
        {!category && (
          <p className="text-xs text-ink-400 mt-2 flex items-center gap-1">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
              strokeLinecap="round" strokeLinejoin="round" className="w-3 h-3">
              <circle cx="12" cy="12" r="10" />
              <path d="M12 16v-4M12 8h.01" />
            </svg>
            Required — the receipt is tagged with this category for the
            dashboard breakdown.
          </p>
        )}
      </div>

      {/* ───────── Dropzone ───────── */}
      <div
        {...getRootProps()}
        className={`relative overflow-hidden rounded-2xl p-10 sm:p-12 text-center transition-all duration-300 cursor-pointer focus-ring
          ${
            isDragActive
              ? "glass-tint ring-2 ring-brand-400"
              : "glass"
          }
          ${disabled ? "opacity-55 pointer-events-none" : "hover:shadow-soft-lg hover:-translate-y-0.5"}`}
      >
        <input {...getInputProps()} />

        {/* Subtle animated halo behind the icon */}
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <div
            className={`w-40 h-40 rounded-full blur-3xl transition-opacity duration-500
              ${isDragActive ? "bg-brand-400/25 opacity-100" : "bg-brand-300/15 opacity-60"}`}
          />
        </div>

        <div className="relative flex flex-col items-center gap-3">
          {/* Upload icon */}
          <div className="relative inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-gradient-to-br from-brand-500/15 to-brand-600/10 text-brand-700">
            {status === "uploading" ? (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                strokeLinecap="round" strokeLinejoin="round" className="w-6 h-6 animate-spin">
                <path d="M21 12a9 9 0 1 1-6.22-8.56" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
                strokeLinecap="round" strokeLinejoin="round" className="w-6 h-6">
                <path d="M12 16V4" />
                <path d="M7 9l5-5 5 5" />
                <path d="M5 16v3a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3" />
              </svg>
            )}
          </div>

          <div>
            <div className="text-base font-semibold text-ink-900">
              {status === "uploading" ? "Uploading to S3…" : headingText}
            </div>
            <div className="text-xs text-ink-400 mt-1">{subText}</div>
          </div>
        </div>
      </div>

      {/* ───────── Status banners ───────── */}
      {status === "uploading" && (
        <div className="flex items-center gap-2.5 text-brand-700 text-sm bg-brand-50/70 border border-brand-200/80 rounded-xl p-3 animate-fade-in">
          <span className="w-4 h-4 rounded-full border-2 border-brand-300 border-t-brand-700 animate-spin" />
          {message || "Uploading to S3…"}
        </div>
      )}

      {status === "success" && (
        <div className="flex items-start gap-2.5 text-emerald-800 text-sm bg-emerald-50/70 border border-emerald-200/80 rounded-xl p-3 animate-fade-in">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
            strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4 mt-0.5 shrink-0">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
            <path d="M22 4L12 14.01l-3-3" />
          </svg>
          <div className="min-w-0">
            <div>{message}</div>
            {s3Key && (
              <div className="mt-1.5 text-xs text-emerald-700/80 break-all font-mono">
                S3 key: {s3Key}
              </div>
            )}
          </div>
        </div>
      )}

      {status === "error" && (
        <div className="flex items-start gap-2.5 text-rose-800 text-sm bg-rose-50/70 border border-rose-200/80 rounded-xl p-3 animate-fade-in">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
            strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4 mt-0.5 shrink-0">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 8v4M12 16h.01" />
          </svg>
          <span>{message}</span>
        </div>
      )}
    </div>
  );
}
