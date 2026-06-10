export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

export type ScoredField<T = string> = {
  value: T;
};

export type Tag = {
  tag_type: string;
  tag_value: string;
};

export type CandidateListItem = {
  resume_identity: string;
  file_name: string;
  name: string;
  job_intent: string;
  location_raw: string;
  project_count: number;
  work_count: number;
};

export type WorkExperience = {
  work_ref: string;
  company_name: string;
  job_title_raw: string;
  start_date: string;
  end_date: string;
  location: string;
  raw_line: string;
};

export type EducationExperience = {
  school_name: string;
  degree: string;
  major: string;
  start_date: string;
  end_date: string;
};

export type WorkProfile = {
  years_label: string;
  total_years: number;
  confidence_label: string;
  domains: string[];
  roles: string[];
  companies: string[];
};

export type Project = {
  project_id: string;
  project_name_raw: string;
  project_source_type: string;
  parent_work_experience_ref: string;
  organization_raw: string;
  date_range_raw: string;
  role_raw: string;
  role_normalized: string;
  tags: Tag[];
};

export type EvidenceChunk = {
  project_id: string;
  project_title: string;
  project_summary: string;
  chunk_text: string;
  organization_raw: string;
  date_range_raw: string;
  project_tags: string[];
};

export type CandidateDetail = {
  resume_identity: string;
  file_name: string;
  name: ScoredField;
  contact: Record<string, ScoredField>;
  job_intent: ScoredField;
  location_raw: ScoredField;
  skills: Tag[];
  languages: Tag[];
  certifications_or_scores: Tag[];
  work_profile?: WorkProfile;
  work_experiences: WorkExperience[];
  education_experiences: EducationExperience[];
  tags: Tag[];
};

export type ClassifiedProjects = {
  resume_identity: string;
  ordinary_projects: Project[];
  work_embedded_projects: Project[];
  work_experiences: WorkExperience[];
  evidence_chunks: EvidenceChunk[];
};

export type SummaryResponse = {
  resume_identity: string;
  summary: string;
  summary_sections: {
    overall_summary: string;
    personal_summary: string;
    project_summary: string;
    work_experience_summary: string;
    strengths: string[];
    risks_or_missing_info: string[];
  };
  llm_error: string;
};

export type ResumeDocument = {
  resume_identity: string;
  file_name: string;
  extension: string;
  mime_type: string;
  preview_kind: "pdf" | "html" | "";
  preview_url: string;
  download_url: string;
  source_available: boolean;
};

export type IngestionResponse = {
  directory: string;
  total_files: number;
  success_count: number;
  error_count: number;
  message: string;
  results: IngestionResult[];
};

export type IngestionResult = {
  file: string;
  status: "ok" | "error";
  error?: string;
  resume_identity?: string;
  replaced_existing_resume?: boolean;
  name?: string;
  work_count?: number;
  education_count?: number;
  project_count?: number;
  storage_blocked_reason?: string;
  storage_blocked_message?: string;
};

export type IngestionStatus = {
  running: boolean;
  phase: string;
  directory: string;
  total_files: number;
  current_index: number;
  current_file: string;
  current_step: string;
  success_count: number;
  error_count: number;
  message: string;
  recent_messages: string[];
};

export type LlmStatus = {
  chat_provider: string;
  display_name: string;
  available: boolean;
  local_available: boolean;
  message: string;
};

export type QAEvidenceRef = {
  source_type: string;
  resume_identity: string;
  candidate_name: string;
  project_id: string;
  project_title: string;
  evidence_id: string;
  text: string;
  summary: string;
  strength: number;
};

export type QACandidateScore = {
  resume_identity: string;
  name: string;
  total_score: number;
  dimension_scores: Record<string, number>;
  strengths: string[];
  risks: string[];
  evidence_refs: QAEvidenceRef[];
  missing_info: string[];
  recommendation_reason?: string;
  tie_break_reason?: string;
};

export type QAAskResponse = {
  status: "ok" | "needs_clarification" | "failed";
  answer: string;
  clarification_required: boolean;
  clarification_question: string;
  clarification_options: string[];
  used_evidence_refs: QAEvidenceRef[];
  ranking: QACandidateScore[];
  comparison_profiles: {
    resume_identity: string;
    name: string;
    job_intent: string;
    work_experiences: WorkExperience[];
    projects: Pick<Project, "project_id" | "project_name_raw" | "organization_raw" | "date_range_raw">[];
  }[];
  comparison_candidate_ids: string[];
  updated_session_context: Record<string, unknown>;
  trace?: {
    trace_id?: string;
    intent?: string | null;
    final_status?: string;
    clarification_required?: boolean;
    diagnosis?: {
      level?: "ok" | "info" | "warning" | "clarification" | "error" | string;
      status?: string;
      headline?: string;
      impact?: string;
      handling?: string;
      suggested_check?: string;
      technical_code?: string;
      failed_node?: string;
      failed_reason?: string;
      route_from?: string;
      route_to?: string;
      route_reason?: string;
      fallbacks?: {
        node?: string;
        fallback_reason?: string;
        repair_action?: string;
        repair_reason?: string;
        error_category?: string;
      }[];
      tool_failures?: {
        tool: string;
        error?: string;
      }[];
      warnings?: string[];
      validation_errors?: {
        plan?: string[];
        execution?: string[];
        answer?: string[];
      };
      trace_lookup?: string;
    };
    decision_steps?: {
      step?: number;
      node?: string;
      engine?: string;
      status?: string;
      summary?: string;
      fallback_reason?: string;
      repair_action?: string;
      repair_reason?: string;
      error_category?: string;
      duration_ms?: number;
      errors?: string[];
      warnings?: string[];
    }[];
    node_details?: Record<string, {
      title?: string;
      input?: Record<string, unknown>;
      decision?: Record<string, unknown>;
      output?: Record<string, unknown>;
      raw?: Record<string, unknown>;
    }>;
    route_events?: {
      step?: number;
      route_from?: string;
      route_to?: string;
      reason?: string;
      errors?: string[];
      retry_count?: number;
    }[];
    tools?: {
      name: string;
      status: "ok" | "failed";
      error?: string;
      warnings?: string[];
    }[];
    validation_errors?: {
      plan?: string[];
      execution?: string[];
      answer?: string[];
    };
    retry_count?: Record<string, number>;
    semantic_plan?: Record<string, unknown> | null;
    compiled_plan?: Record<string, unknown> | null;
    compiler_decision?: {
      compiler_mode?: string;
      compiler_config_mode?: string;
      compiler_strategy?: string;
      compiler_source?: string;
      compiler_enabled_flags?: Record<string, unknown>;
      selection_rule?: string;
      hint_tool_decisions?: {
        tool: string;
        intents?: string[];
        confidence?: number;
        source?: string;
        decision?: string;
        reason?: string;
        final_tool_call_index?: number;
        artifact_id?: string;
      }[];
      final_tool_calls?: {
        index: number;
        name: string;
        output_key?: string;
        depends_on?: string[];
      }[];
    };
    session_context_snapshot?: {
      before_keys?: string[];
      after_keys?: string[];
      current?: Record<string, unknown>;
    };
    graph?: {
      nodes: {
        id: string;
        label: string;
        kind: "router" | "planner" | "validator" | "executor" | "answer" | "terminal";
      }[];
      edges: {
        from: string;
        to: string;
        label?: string;
      }[];
      visited: string[];
      active_edges: {
        from: string;
        to: string;
        label?: string;
      }[];
      node_status: Record<string, "ok" | "repair" | "failed" | "clarification" | "final">;
    };
    log_file_hint?: string;
  } | null;
};

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const method = init?.method?.toUpperCase() || "GET";
  const url = new URL(`${API_BASE}${path}`);
  if (method === "GET") {
    url.searchParams.set("_ts", Date.now().toString());
  }
  const response = await fetch(url.toString(), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-cache, no-store, must-revalidate",
      Pragma: "no-cache",
      ...(init?.headers || {}),
    },
    cache: "no-store",
    next: { revalidate: 0 },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json();
}

export async function getCandidates() {
  return apiFetch<{ candidates: CandidateListItem[] }>("/candidates");
}

export async function getCandidateDetail(resumeIdentity: string) {
  return apiFetch<CandidateDetail>(`/candidates/${encodeURIComponent(resumeIdentity)}`);
}

export async function getCandidateProjects(resumeIdentity: string) {
  return apiFetch<ClassifiedProjects>(`/candidates/${encodeURIComponent(resumeIdentity)}/projects`);
}

export async function getCandidateResumeDocument(resumeIdentity: string) {
  return apiFetch<ResumeDocument>(`/candidates/${encodeURIComponent(resumeIdentity)}/resume-document`);
}

export function toApiUrl(pathOrUrl: string) {
  if (!pathOrUrl) return "";
  if (/^https?:\/\//i.test(pathOrUrl)) return pathOrUrl;
  return `${API_BASE}${pathOrUrl}`;
}

export async function generateCandidateSummary(resumeIdentity: string) {
  return apiFetch<SummaryResponse>(`/candidates/${encodeURIComponent(resumeIdentity)}/summary`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function ingestResumeFiles(directory = "resume_query_v3/resume") {
  return apiFetch<IngestionResponse>("/ingestion/resumes", {
    method: "POST",
    body: JSON.stringify({ directory }),
  });
}

export async function getIngestionStatus() {
  return apiFetch<IngestionStatus>("/ingestion/status");
}

export async function getLlmStatus() {
  return apiFetch<LlmStatus>("/llm/status");
}

export async function askResumeQa(payload: {
  question: string;
  session_context?: Record<string, unknown>;
  use_llm?: boolean;
  debug?: boolean;
}) {
  return apiFetch<QAAskResponse>("/qa/ask", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
