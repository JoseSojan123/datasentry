import { FileUp, FileX2, X } from "lucide-react";
import { useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { fmtBytes } from "@/lib/format";

export const MAX_UPLOAD_MB = 25;
const OK_EXT = ["csv", "txt", "parquet", "pq"];

export function validateFile(f: File): string | null {
  const ext = f.name.split(".").pop()?.toLowerCase() ?? "";
  if (!OK_EXT.includes(ext)) return `“.${ext}” files are not supported. Upload a .csv or .parquet file.`;
  if (f.size === 0) return "This file is empty.";
  if (f.size > MAX_UPLOAD_MB * 1024 * 1024) return `This file is ${fmtBytes(f.size)}; the limit is ${MAX_UPLOAD_MB} MB.`;
  return null;
}

export function Dropzone({ file, onFile, progress, disabled }: { file: File | null; onFile: (f: File | null) => void; progress?: number | null; disabled?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const accept = (f: File | undefined) => {
    if (!f) return;
    const err = validateFile(f);
    setError(err);
    onFile(err ? null : f);
  };

  return (
    <div>
      <div
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-disabled={disabled}
        aria-label={file ? `Selected file ${file.name}. Press to choose a different file.` : "Choose a CSV or Parquet file, or drop it here"}
        onClick={() => !disabled && input.current?.click()}
        onKeyDown={(e) => {
          if (!disabled && (e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            input.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          if (!disabled) accept(e.dataTransfer.files?.[0]);
        }}
        className={cn(
          "relative flex min-h-[148px] cursor-pointer flex-col items-center justify-center gap-2 overflow-hidden rounded-lg border border-dashed px-4 py-6 text-center transition-colors",
          drag ? "border-accent bg-accent/[0.06]" : error ? "border-crit/60 bg-crit/[0.04]" : "border-line-strong bg-bg hover:border-accent/60",
          disabled && "cursor-not-allowed opacity-70",
        )}
      >
        {file ? (
          <>
            <FileUp className="h-6 w-6 text-accent" aria-hidden />
            <div className="max-w-full truncate font-mono text-base text-fg">{file.name}</div>
            <div className="text-sm text-muted">{fmtBytes(file.size)}</div>
            {!disabled && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onFile(null);
                  setError(null);
                  if (input.current) input.current.value = "";
                }}
                className="absolute right-2 top-2 rounded p-1 text-faint hover:bg-overlay hover:text-fg"
                aria-label="Remove file"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </>
        ) : (
          <>
            {error ? <FileX2 className="h-6 w-6 text-crit" aria-hidden /> : <FileUp className="h-6 w-6 text-faint" aria-hidden />}
            <div className="text-base text-fg">
              <span className="text-accent">Choose a file</span> or drag it here
            </div>
            <div className="text-sm text-muted">CSV or Parquet, up to {MAX_UPLOAD_MB} MB. The CSV delimiter is detected automatically.</div>
          </>
        )}
        {progress !== null && progress !== undefined && (
          <div className="absolute inset-x-0 bottom-0 h-1 bg-overlay" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)} aria-label="Upload progress">
            <div className="h-full bg-accent transition-[width] duration-200" style={{ width: `${progress * 100}%` }} />
          </div>
        )}
      </div>
      {error && (
        <p role="alert" className="mt-1.5 text-sm text-crit">
          {error}
        </p>
      )}
      <input ref={input} type="file" accept=".csv,.txt,.parquet,.pq" className="sr-only" tabIndex={-1} aria-hidden onChange={(e) => accept(e.target.files?.[0])} />
    </div>
  );
}
