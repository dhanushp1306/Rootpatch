import { useCallback, useState } from "react";

const REGISTRY_STORAGE_KEY = "rootpatch.known_projects.v1";
const ACTIVE_PROJECT_STORAGE_KEY = "rootpatch.active_project_id.v1";

export interface KnownProjectSummary {
  project_id: string;
  project_name: string;
  added_at: string;
}

function readKnownProjects(): KnownProjectSummary[] {
  try {
    const raw = window.localStorage.getItem(REGISTRY_STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter(
      (item): item is KnownProjectSummary =>
        Boolean(item) &&
        typeof (item as KnownProjectSummary).project_id === "string" &&
        typeof (item as KnownProjectSummary).project_name === "string"
    );
  } catch {
    return [];
  }
}

function readActiveProjectId(): string | null {
  try {
    const val = window.localStorage.getItem(ACTIVE_PROJECT_STORAGE_KEY);
    return val && val.trim() ? val.trim() : null;
  } catch {
    return null;
  }
}

export function useProjectRegistry() {
  const [knownProjects, setKnownProjects] = useState<KnownProjectSummary[]>(() =>
    readKnownProjects()
  );
  const [activeProjectId, setActiveProjectIdState] = useState<string | null>(() => {
    const stored = readActiveProjectId();
    if (stored) {
      return stored;
    }
    const known = readKnownProjects();
    return known[0]?.project_id ?? null;
  });

  const setActiveProjectId = useCallback((projectId: string | null) => {
    setActiveProjectIdState(projectId);
    try {
      if (projectId) {
        window.localStorage.setItem(ACTIVE_PROJECT_STORAGE_KEY, projectId);
      } else {
        window.localStorage.removeItem(ACTIVE_PROJECT_STORAGE_KEY);
      }
    } catch {
      // Ignore storage failures in restricted contexts
    }
  }, []);

  const registerProject = useCallback(
    (projectId: string, projectName: string) => {
      setKnownProjects((prev) => {
        const filtered = prev.filter((p) => p.project_id !== projectId);
        const next: KnownProjectSummary[] = [
          {
            project_id: projectId,
            project_name: projectName,
            added_at: new Date().toISOString(),
          },
          ...filtered,
        ].slice(0, 25);
        try {
          window.localStorage.setItem(REGISTRY_STORAGE_KEY, JSON.stringify(next));
        } catch {
          // Ignore storage failures
        }
        return next;
      });
      setActiveProjectId(projectId);
    },
    [setActiveProjectId]
  );

  const removeKnownProject = useCallback(
    (projectId: string) => {
      setKnownProjects((prev) => {
        const next = prev.filter((p) => p.project_id !== projectId);
        try {
          window.localStorage.setItem(REGISTRY_STORAGE_KEY, JSON.stringify(next));
        } catch {
          // Ignore
        }
        if (activeProjectId === projectId) {
          setActiveProjectId(next[0]?.project_id ?? null);
        }
        return next;
      });
    },
    [activeProjectId, setActiveProjectId]
  );

  return {
    knownProjects,
    activeProjectId,
    setActiveProjectId,
    registerProject,
    removeKnownProject,
  };
}
