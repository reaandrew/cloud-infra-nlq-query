import { useEffect, useState } from "react";
import { AppShell, type ViewId } from "./components/AppShell";
import { ApiKeyDialog } from "./components/ApiKeyDialog";
import { QueryView } from "./views/QueryView";
import { HowItWorksView } from "./views/HowItWorksView";
import { HowThisWasMadeView } from "./views/HowThisWasMadeView";
import { getStoredApiKey } from "./lib/api";

function App() {
  const [view, setView] = useState<ViewId>("query");
  const [hasApiKey, setHasApiKey] = useState<boolean>(() => !!getStoredApiKey());
  const [apiKeyDialogOpen, setApiKeyDialogOpen] = useState(false);

  // Re-read on storage events (multi-tab)
  useEffect(() => {
    const onStorage = () => setHasApiKey(!!getStoredApiKey());
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  // Scroll to top whenever the view changes
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [view]);

  return (
    <>
      <AppShell
        view={view}
        onViewChange={setView}
        apiKeyStatus={hasApiKey ? "ok" : "missing"}
        onOpenApiKeyDialog={() => setApiKeyDialogOpen(true)}
      >
        {view === "query" && (
          <QueryView
            hasApiKey={hasApiKey}
            onRequireApiKey={() => setApiKeyDialogOpen(true)}
          />
        )}
        {view === "how-it-works" && <HowItWorksView />}
        {view === "how-this-was-made" && <HowThisWasMadeView />}
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
