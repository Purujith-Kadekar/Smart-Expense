// Standalone UploadDropzone component — kept for parity with the original
// project structure (it isn't imported by Upload.jsx, which uses
// react-dropzone inline, but the file is here in case it's referenced by
// docs or future pages).
//
// API surface preserved: props = { onUpload, disabled }.
// Only the visual treatment is new.
import { useDropzone } from "react-dropzone";

export default function UploadDropzone({ onUpload, disabled }) {
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop: (files) => onUpload(files[0]),
    accept: { "image/*": [".jpg", ".jpeg", ".png", ".heic"] },
    multiple: false,
    disabled,
  });

  return (
    <div
      {...getRootProps()}
      className={`relative overflow-hidden rounded-2xl p-10 text-center transition-all duration-300 cursor-pointer focus-ring
        ${isDragActive
          ? "glass-tint ring-2 ring-brand-400"
          : "glass hover:shadow-soft-lg hover:-translate-y-0.5"}
        ${disabled ? "opacity-55 pointer-events-none" : ""}`}
    >
      <input {...getInputProps()} />

      <div className="relative flex flex-col items-center gap-3">
        <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-brand-500/15 to-brand-600/10 text-brand-700">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
            strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
            <path d="M12 16V4M7 9l5-5 5 5M5 16v3a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3" />
          </svg>
        </div>
        <div className="text-sm font-semibold text-ink-900">
          {isDragActive ? "Drop the file here…" : "Drag & drop a receipt photo here"}
        </div>
        <div className="text-xs text-ink-400">JPG, JPEG, PNG, HEIC</div>
      </div>
    </div>
  );
}
