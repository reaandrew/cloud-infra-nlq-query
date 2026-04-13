import { useEffect, useState } from "react";
import { AppShell, type ViewId } from "./components/AppShell";
import { ApiKeyDialog } from "./components/ApiKeyDialog";
import { DashboardView } from "./views/DashboardView";
import { QueryView } from "./views/QueryView";
import { getStoredApiKey } from "./lib/api";

function App() {
  const [view, setView] = useState<ViewId>("dashboard");
  const [hasApiKey, setHasApiKey] = useState<boolean>(() => !!getStoredApiKey());
  const [apiKeyDialogOpen, setApiKeyDialogOpen] = useState(false);

  // No mandatory dialog at startup — the dashboard works without an API key
  // because the /stats/* endpoints are open. We only nag when the user tries
  // to ask a question and doesn't have a key.

  // Re-read on storage events (multi-tab)
  useEffect(() => {
    const onStorage = () => setHasApiKey(!!getStoredApiKey());
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  return (
    <>
      <AppShell
        view={view}
        onViewChange={setView}
        apiKeyStatus={hasApiKey ? "ok" : "missing"}
        onOpenApiKeyDialog={() => setApiKeyDialogOpen(true)}
      >
        {view === "dashboard" && <DashboardView />}
        {view === "query" && (
          <QueryView
            hasApiKey={hasApiKey}
            onRequireApiKey={() => setApiKeyDialogOpen(true)}
          />
        )}
      </AppShell>

      <ApiKeyDialog
        open={apiKeyDialogOpen}
        onClose={() => setApiKeyDialogOpen(false)}
        onSaved={() => setHasApiKey(!!getStoredApiKey())}
      />
    </>
  );
}

export default App;
