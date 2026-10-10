import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/cn";

export function CodeBlock({ code, className, language, copy = true }: { code: string; className?: string; language?: string; copy?: boolean }) {
  const [done, setDone] = useState(false);
  return (
    <div className={cn("group relative rounded-md border border-line bg-bg", className)}>
      {language && <div className="label border-b border-line px-3 py-1.5">{language}</div>}
      <pre className="overflow-x-auto p-3 font-mono text-sm leading-relaxed text-muted">
        <code>{code}</code>
      </pre>
      {copy && (
        <button
          onClick={() => {
            void navigator.clipboard?.writeText(code).then(() => {
              setDone(true);
              setTimeout(() => setDone(false), 1500);
            });
          }}
          aria-label="Copy to clipboard"
          className="absolute right-2 top-2 rounded border border-line bg-surface p-1.5 text-faint opacity-0 transition-opacity hover:text-fg focus:opacity-100 group-hover:opacity-100"
          style={language ? { top: 36 } : undefined}
        >
          {done ? <Check className="h-3.5 w-3.5 text-ok" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
      )}
    </div>
  );
}

export function JsonView({ value, className }: { value: unknown; className?: string }) {
  return <CodeBlock code={JSON.stringify(value, null, 2)} className={className} />;
}
