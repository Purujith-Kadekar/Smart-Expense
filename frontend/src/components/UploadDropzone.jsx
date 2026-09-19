// Standalone UploadDropzone component (currently the Upload page uses
// react-dropzone inline — this file is here in case the docs' structure
// is enforced for the demo, e.g. if a teammate wants to embed the dropzone
// into the Dashboard page directly).
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
      className={`border-2 border-dashed rounded-lg p-10 text-center cursor-pointer transition-colors
        ${isDragActive ? "border-brand-500 bg-brand-50" : "border-slate-300 bg-white"}
        ${disabled ? "opacity-60 pointer-events-none" : ""}`}
    >
      <input {...getInputProps()} />
      <div className="text-slate-700 font-medium">
        {isDragActive ? "Drop the file here…" : "Drag & drop a receipt photo here"}
      </div>
    </div>
  );
}
