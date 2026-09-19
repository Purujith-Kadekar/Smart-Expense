import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import api from "../api/client.js";

// Single-file drag-and-drop upload page.
// Flow: user picks a category → drops a file → we ask Flask for a presigned
// PUT URL (with category in the body, user_id from the JWT) → we PUT the
// file bytes directly to S3 → S3's ObjectCreated event triggers the Lambda
// ingestion pipeline → the dashboard shows the new expense once OCR
// finishes processing.
//
// The S3 key format is `receipts/{user_id}/{category}/{uuid}_{filename}` —
// Lambda parses user_id + category back out of the key path because Lambda
// never talks to Flask.
const CATEGORIES = [
  { value: "", label: "Select a category…" },
  { value: "college", label: "College" },
  { value: "mess", label: "Mess" },
  { value: "event", label: "Event" },
  { value: "other", label: "Other" },
];

export default function Upload() {
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("idle"); // idle | uploading | success | error
  const [message, setMessage] = useState("");
  const [s3Key, setS3Key] = useState("");

  const onDrop = useCallback(
    async (acceptedFiles) => {
      if (!category) {
        // Defensive — the dropzone is disabled until a category is picked,
        // but a race condition could still trigger this.
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
        // 1. Ask Flask for a presigned PUT URL. The request interceptor in
        // api/client.js attaches the Authorization header automatically.
        // `category` travels in the body; user_id is read from the JWT
        // server-side and baked into the S3 key.
        const { data } = await api.post("/upload-url", {
          filename: file.name,
          category,
        });
        const { upload_url, s3_key } = data;

        // 2. PUT the file directly to S3 — bypasses Flask entirely so
        // backend memory stays flat regardless of image size.
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

        // 3. Trigger OCR processing. In docker-compose mode (LocalStack),
        //    the backend invokes the Lambda handler directly with a synthetic
        //    S3 event. In real AWS, this is a no-op (S3 triggers Lambda
        //    automatically). Either way, the dashboard will show the new
        //    receipt within a few seconds.
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
          // OCR trigger failed, but the upload itself succeeded — don't
          // show this as a hard error, the receipt is in S3.
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
    // Disable the dropzone until a category is selected — the S3 key path
    // requires a category, so an upload without one would 400 anyway. Better
    // UX to prevent the drop than to show an error after the fact.
    disabled: !category || status === "uploading",
  });

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-slate-900">
          Upload a receipt
        </h2>
        <p className="text-sm text-slate-500 mt-1">
          Pick a category, then drop a receipt photo. It will be uploaded to
          S3 and processed by OCR automatically — vendor and total are
          extracted without any manual entry.
        </p>
      </div>

      {/* Category selector — required before the dropzone activates. */}
      <div>
        <label
          htmlFor="category"
          className="block text-sm font-medium text-slate-700 mb-1"
        >
          Category <span className="text-red-600">*</span>
        </label>
        <select
          id="category"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="w-full max-w-xs px-3 py-2 border border-slate-300 rounded-md bg-white focus:outline-none focus:ring-2 focus:ring-brand-500"
        >
          {CATEGORIES.map((c) => (
            <option key={c.value} value={c.value} disabled={!c.value}>
              {c.label}
            </option>
          ))}
        </select>
        {!category && (
          <p className="text-xs text-slate-400 mt-1">
            Required — the receipt is tagged with this category for the
            dashboard breakdown.
          </p>
        )}
      </div>

      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-lg p-10 text-center transition-colors
          ${
            isDragActive
              ? "border-brand-500 bg-brand-50"
              : "border-slate-300 bg-white"
          }
          ${
            !category || status === "uploading"
              ? "opacity-60 pointer-events-none"
              : "cursor-pointer"
          }`}
      >
        <input {...getInputProps()} />
        <div className="text-slate-700 font-medium">
          {isDragActive
            ? "Drop the file here…"
            : !category
            ? "Pick a category above to enable upload"
            : "Drag & drop a receipt photo here"}
        </div>
        <div className="text-xs text-slate-400 mt-1">
          JPG, JPEG, PNG, HEIC — single file only
        </div>
      </div>

      {status === "uploading" && (
        <div className="text-brand-700 text-sm">Uploading to S3…</div>
      )}
      {status === "success" && (
        <div className="bg-green-50 border border-green-200 text-green-800 text-sm rounded-md p-3">
          {message}
          {s3Key && (
            <div className="mt-2 text-xs text-green-700 break-all">
              S3 key: {s3Key}
            </div>
          )}
        </div>
      )}
      {status === "error" && (
        <div className="bg-red-50 border border-red-200 text-red-800 text-sm rounded-md p-3">
          {message}
        </div>
      )}
    </div>
  );
}
