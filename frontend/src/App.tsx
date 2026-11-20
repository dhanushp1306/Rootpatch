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

  const { knownProjects, activeProjectId, setActiveProjectId, registerProject, removeKnownProject } =
    useProjectRegistry();

  const workspace = useProjectWorkspace(activeProjectId, client);

  // Selecting a project only changes the active id; the workspace hook performs the
  // (single) load, so no extra getProject request is issued here.
  const handleSelectProject = (projectId: string) => {
    setActiveProjectId(projectId);
  };

  // Registering makes the new project active, which triggers exactly one workspace load.
  const handleProjectReady = (metadata: ProjectMetadata) => {
    registerProject(metadata.project_id, metadata.project_name);
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
      onSelectProject={handleSelectProject}
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
        {workspace.error && workspace.errorCode === "project_not_found" ? (
          <StateBanner
            variant="error"
            title="Project Not Found"
            message={workspace.error}
            action={
              activeProjectId ? (
                <button
                  type="button"
                  onClick={() => removeKnownProject(activeProjectId)}
                  className="rounded-lg border border-red-300 bg-[#DCD7F2] px-3 py-1.5 text-xs font-semibold text-[#D9485B] hover:bg-red-50 whitespace-nowrap"
                >
                  Remove from Recent Projects
                </button>
              ) : undefined
            }
          />
        ) : workspace.error ? (
          <StateBanner
            variant="error"
            title="Workspace Error"
            message={workspace.error}
            action={
              <button
                type="button"
                onClick={() => {
                  void workspace.refreshAll();
                }}
                className="rounded-lg border border-red-300 bg-[#DCD7F2] px-3 py-1.5 text-xs font-semibold text-[#D9485B] hover:bg-red-50 whitespace-nowrap"
              >
                Retry
              </button>
            }
          />
        ) : null}

        {Object.entries(workspace.resourceErrors).map(([key, message]) => (
          <StateBanner
            key={key}
            variant="warning"
            title={`Could not load ${key}`}
            message={message}
          />
        ))}

        {workspace.loading && !workspace.project && activeSection !== "upload" ? (
          <LoadingState label="Loading project workspace..." />
        ) : null}

        {activeSection === "dashboard" ? (
          <DashboardPage
            workspace={workspace}
            knownProjects={knownProjects}
            onSelectProject={handleSelectProject}
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
            patches={workspace.patches}
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
            analysis={workspace.analysis}
            onPatchesGenerated={workspace.setPatches}
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
