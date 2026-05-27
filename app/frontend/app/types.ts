export interface SseEvent {
  type:
    | "token"
    | "incident_detected"
    | "step_start"
    | "step_complete"
    | "result"
    | "error";
  data: unknown;
}

export interface TokenData {
  author: string;
  text: string;
}

export interface IncidentAnchors {
  postcode: string | null;
  voltage_class: string | null;
  asset_class: string | null;
  incident_summary: string | null;
  vwi_codes: string[];
  crew_shortlist: string[];
  candidate_raamopdrachten?: string[];
  free_text_nl?: string;
}

export interface StepData {
  agent: string;
  summary?: string;
}

export interface DispatchResult {
  incident_id?: string | null;
  incident_summary?: string;
  vwis?: { vwi_id: string; confidence: "confirmed" | "candidate" }[];
  matched_crew?: string;
  matched_raamopdracht_id?: string;
  coverage_status?: "covered" | "partial" | "not_covered" | "unknown";
  review_status?: "pass" | "revise" | "flagged_for_human_review";
  operational_action?: "dispatch_ok" | "wv_escalation_needed";
  rule_verdicts?: { rule_id: string; pass: boolean; reason: string }[];
  review_findings?: { criterion: string; verdict: "pass" | "fail"; reason: string }[];
  rationale?: string;
  wv_escalation_reason?: string | null;
  revision_count?: number;
  citations?: {
    vwi_refs?: string[];
    raamopdracht_scope_excerpts?: string[];
    bei_rule_refs?: string[];
  };
  raw?: string;
}
