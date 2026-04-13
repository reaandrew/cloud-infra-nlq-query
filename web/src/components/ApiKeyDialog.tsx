import { useState, useEffect } from "react";
import { KeyRound, ShieldCheck, Trash2 } from "lucide-react";
import { Dialog } from "./ui/Dialog";
import { Button } from "./ui/Button";
import { getStoredApiKey, setStoredApiKey } from "../lib/api";

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  initiallyMandatory?: boolean;
}

export function ApiKeyDialog({ open, onClose, onSaved, initiallyMandatory }: Props) {
  const [value, setValue] = useState("");
  const hasExisting = !!getStoredApiKey();

  // Reset the field when the dialog opens
  useEffect(() => {
    if (open) setValue(getStoredApiKey());
  }, [open]);

  const save = () => {
    setStoredApiKey(value.trim());
    onSaved();
    onClose();
  };

  const clear = () => {
    setStoredApiKey("");
    setValue("");
    onSaved();
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      closeable={!initiallyMandatory || hasExisting}
      title="Set your API key"
      description="The /nlq endpoint requires an x-api-key header. Get it via `make api-key` from the project root, or `aws secretsmanager get-secret-value` against the secret named cloud-infra-nlq-query-nlq-api-key."
    >
      <div className="space-y-4">
        <label className="block">
          <span className="text-xs font-semibold text-[var(--color-fg-muted)] uppercase tracking-wider">
            x-api-key
          </span>
          <div className="mt-1 relative">
            <KeyRound
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-fg-muted)]"
            />
            <input
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="paste your key"
              className="w-full pl-8 pr-3 py-2.5 text-sm font-mono rounded-lg border border-[var(--color-border-subtle)] focus:border-[var(--color-accent-500)] focus:ring-2 focus:ring-[var(--color-accent-500)]/20 focus:outline-none transition"
              onKeyDown={(e) => {
                if (e.key === "Enter" && value.trim()) save();
              }}
            />
          </div>
        </label>

        <div className="bg-[var(--color-bg-app)] border border-[var(--color-border-subtle)] rounded-lg p-3 flex items-start gap-2.5">
          <ShieldCheck size={14} className="text-[var(--color-fg-muted)] shrink-0 mt-0.5" />
          <p className="text-[12px] text-[var(--color-fg-muted)] leading-relaxed">
            Stored only in your browser&apos;s localStorage. Never sent anywhere
            except the <code className="px-1 rounded bg-white">x-api-key</code>{" "}
            header to the cinq API.
          </p>
        </div>

        <div className="flex items-center justify-between pt-2">
          {hasExisting ? (
            <Button variant="ghost" size="sm" onClick={clear}>
              <Trash2 size={14} />
              Clear
            </Button>
          ) : (
            <span />
          )}
          <div className="flex items-center gap-2">
            {(!initiallyMandatory || hasExisting) && (
              <Button variant="secondary" size="md" onClick={onClose}>
                Cancel
              </Button>
            )}
            <Button onClick={save} disabled={!value.trim()}>
              Save key
            </Button>
          </div>
        </div>
      </div>
    </Dialog>
  );
}
