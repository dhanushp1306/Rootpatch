import { useState } from "react";
import { AppShell, type NavSection } from "./components/AppShell";
import { LoadingState, StateBanner } from "./components/StateBanner";
import { useProjectRegistry } from "./hooks/useProjectRegistry";
import { useProjectWorkspace } from "./hooks/useProjectWorkspace";
import { DashboardPage } from "./pages/DashboardPage";
import { FindingsPage } from "./pages/FindingsPage";
import { HistoryPage } from "./pages/HistoryPage";
import { PatchReviewPage } from "./pages/PatchReviewPage";
import { StructurePage } from "./pages/StructurePage";
import { UploadPage } from "./pages/UploadPage";
import { ValidationPage } from "./pages/ValidationPage";
import { RootPatchApiClient, apiClient } from "./services/apiClient";
import type { ProjectMetadata } from "./types/api";

interface AppProps {
  client?: RootPatchApiClient;
  initialSection?: NavSection;
}

export function App({ client = apiClient, initialSection = "dashboard" }: AppProps) {
  const [activeSection, setActiveSection] = useState<NavSection>(initialSection);
  const [preferredValidationPatchId, setPreferredValidationPatchId] = useState<string | null>(null);

  const { knownProjects, activeProjectId, setActiveProjectId, registerProject } =
    useProjectRegistry();

  const workspace = useProjectWorkspace(activeProjectId, client);

  const handleSelectProject = async (projectId: string) => {
    setActiveProjectId(projectId);
    try {
      const metadata = await client.getProject(projectId);
      registerProject(metadata.project_id, metadata.project_name);
    } catch {
      // workspace hook handles and displays load error
    }
  };

  const handleProjectReady = (metadata: ProjectMetadata) => {
    registerProject(metadata.project_id, metadata.project_name);
    void workspace.refreshAll();
  };

  const counts = {
    findings: workspace.scan?.total_findings ?? 0,
    patches: workspace.patches?.patches.length ?? 0,
    validations: workspace.validations?.total_runs ?? 0,
  };

  return (
    <AppShell
      activeSection={activeSection}
      onNavigate={setActiveSection}
      knownProjects={knownProjects}
      activeProjectId={activeProjectId}
      onSelectProject={(id) => {
        void handleSelectProject(id);
      }}
      project={workspace.project}
      health={workspace.health}
      healthError={workspace.healthError}
      onRefresh={() => {
        void workspace.refreshAll();
      }}
      refreshing={workspace.loading}
      counts={counts}
    >
      <div className="space-y-4">
        {workspace.error ? (
          <StateBanner
            variant="error"
            title="Workspace Error"
            message={workspace.error}
          />
        ) : null}

        {workspace.loading && !workspace.project && activeSection !== "upload" ? (
          <LoadingState label="Loading project workspace..." />
        ) : null}

        {activeSection === "dashboard" ? (
          <DashboardPage
            workspace={workspace}
            knownProjects={knownProjects}
            onSelectProject={(id) => {
              void handleSelectProject(id);
            }}
            onNavigate={setActiveSection}
          />
        ) : null}

        {activeSection === "upload" ? (
          <UploadPage
            client={client}
            activeProject={workspace.project}
            onProjectReady={handleProjectReady}
            onContinueToStructure={() => setActiveSection("structure")}
            onContinueToScan={() => setActiveSection("findings")}
          />
        ) : null}

        {activeSection === "structure" ? (
          <StructurePage
            project={workspace.project}
            structure={workspace.structure}
            loading={workspace.loading}
            onGoToUpload={() => setActiveSection("upload")}
          />
        ) : null}

        {activeSection === "findings" ? (
          <FindingsPage
            client={client}
            project={workspace.project}
            scan={workspace.scan}
            analysis={workspace.analysis}
            onScanComplete={workspace.setScan}
            onAnalysisComplete={workspace.setAnalysis}
            onPatchesGenerated={(batch) => {
              workspace.setPatches(batch);
            }}
            onGoToUpload={() => setActiveSection("upload")}
            onGoToPatches={() => setActiveSection("patches")}
          />
        ) : null}

        {activeSection === "patches" ? (
          <PatchReviewPage
            client={client}
            project={workspace.project}
            patches={workspace.patches}
            onPatchesUpdated={workspace.refreshAll}
            onValidatePatch={(patchId) => {
              setPreferredValidationPatchId(patchId);
              setActiveSection("validation");
            }}
            onGoToFindings={() => setActiveSection("findings")}
            onGoToUpload={() => setActiveSection("upload")}
          />
        ) : null}

        {activeSection === "validation" ? (
          <ValidationPage
            client={client}
            project={workspace.project}
            patches={workspace.patches}
            preferredPatchId={preferredValidationPatchId}
            onValidationComplete={workspace.refreshAll}
            onGoToPatches={() => setActiveSection("patches")}
            onGoToUpload={() => setActiveSection("upload")}
          />
        ) : null}

        {activeSection === "history" ? (
          <HistoryPage
            project={workspace.project}
            patchHistory={workspace.patchHistory}
            validations={workspace.validations}
            loading={workspace.loading}
            onGoToUpload={() => setActiveSection("upload")}
          />
        ) : null}
      </div>
    </AppShell>
  );
}

export default App;
