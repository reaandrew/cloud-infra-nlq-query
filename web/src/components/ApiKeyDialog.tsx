import { useState, useEffect } from "react";
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
      description="The Query view talks to a private endpoint that requires an x-api-key header. The key is stored in this browser only — it is never sent anywhere else."
    >
      <div className="space-y-5">
        <label htmlFor="api-key-input" className="block">
          <span className="block text-[19px] font-bold mb-2">x-api-key</span>
          <input
            id="api-key-input"
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="paste your key"
            className="w-full px-3 py-2 text-[19px] font-mono border-2 border-[var(--color-text)] focus:outline-none"
            onKeyDown={(e) => {
              if (e.key === "Enter" && value.trim()) save();
            }}
          />
        </label>

        <div className="border-l-[10px] border-[var(--color-blue)] bg-[var(--color-bg-grey)] p-4">
          <p className="text-[16px] text-[var(--color-text)]">
            <strong className="font-bold">How to get a key:</strong> the demo
            owner generates one on request from AWS Secrets Manager. This is a
            shared demo key with rate limiting — the dashboard works without
            it.
          </p>
        </div>

        <div className="flex items-center justify-between flex-wrap gap-3">
          {hasExisting ? (
            <Button variant="warning" onClick={clear}>
              Clear key
            </Button>
          ) : (
            <span />
          )}
          <div className="flex items-center gap-3">
            {(!initiallyMandatory || hasExisting) && (
              <Button variant="secondary" onClick={onClose}>
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
