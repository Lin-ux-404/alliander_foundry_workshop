"use client";

import { DispatchResult } from "../types";

interface Props {
  result: DispatchResult;
}

function StatusBadge({ ok, labelOk, labelFail }: { ok: boolean; labelOk: string; labelFail: string }) {
  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${
        ok
          ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
          : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
      }`}
    >
      {ok ? `✓ ${labelOk}` : `✗ ${labelFail}`}
    </span>
  );
}

function CoverageStatusBadge({ status }: { status?: string }) {
  const colors: Record<string, string> = {
    covered: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
    partial: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400",
    not_covered: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
    unknown: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400",
  };
  const labels: Record<string, string> = {
    covered: "Volledig gedekt",
    partial: "Gedeeltelijk gedekt",
    not_covered: "Niet gedekt",
    unknown: "Onbekend",
  };
  const key = status || "unknown";
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${colors[key] || colors.unknown}`}>
      {labels[key] || key}
    </span>
  );
}

function OperationalActionBadge({ action }: { action?: string }) {
  const isOk = action === "dispatch_ok";
  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${
        isOk
          ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
          : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
      }`}
    >
      {isOk ? "✓ Dispatch OK" : "⚠ WV escalatie vereist"}
    </span>
  );
}

function ReviewStatusBadge({ status }: { status?: string }) {
  const colors: Record<string, string> = {
    pass: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
    revise: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400",
    flagged_for_human_review: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  };
  const labels: Record<string, string> = {
    pass: "✓ Goedgekeurd",
    revise: "↻ Herzien",
    flagged_for_human_review: "⚠ Menselijke beoordeling",
  };
  const key = status || "pass";
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${colors[key] || colors.pass}`}>
      {labels[key] || key}
    </span>
  );
}

function ConfidenceBadge({ confidence }: { confidence: string }) {
  const isConfirmed = confidence === "confirmed";
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
        isConfirmed
          ? "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400"
          : "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"
      }`}
    >
      {isConfirmed ? "confirmed" : "candidate"}
    </span>
  );
}

export default function ResultCard({ result }: Props) {
  return (
    <div className="rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-700 dark:bg-zinc-900 space-y-6 animate-in fade-in duration-300">
      {/* Header with status badges */}
      <div className="flex flex-col gap-3">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
              Dispatch Aanbeveling
            </h2>
            {result.incident_summary && (
              <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
                {result.incident_summary}
              </p>
            )}
          </div>
          <OperationalActionBadge action={result.operational_action} />
        </div>

        {/* Three status badges */}
        <div className="flex flex-wrap gap-2">
          <CoverageStatusBadge status={result.coverage_status} />
          <ReviewStatusBadge status={result.review_status} />
          {result.revision_count != null && result.revision_count > 0 && (
            <span className="inline-block rounded-full bg-zinc-100 px-2.5 py-0.5 text-xs font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
              {result.revision_count} herzien{result.revision_count > 1 ? "ingen" : "ing"}
            </span>
          )}
        </div>
      </div>

      {/* WV escalation reason */}
      {result.wv_escalation_reason && (
        <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 dark:bg-red-950/20 dark:border-red-900/40 dark:text-red-400">
          {result.wv_escalation_reason}
        </div>
      )}

      {/* Matched crew + RO */}
      {(result.matched_crew || result.matched_raamopdracht_id) && (
        <section className="flex flex-wrap gap-4">
          {result.matched_crew && (
            <div>
              <span className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Bemanning</span>
              <p className="mt-0.5 text-sm font-mono text-zinc-800 dark:text-zinc-200">{result.matched_crew}</p>
            </div>
          )}
          {result.matched_raamopdracht_id && (
            <div>
              <span className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Raamopdracht</span>
              <p className="mt-0.5 text-sm font-mono text-zinc-800 dark:text-zinc-200">{result.matched_raamopdracht_id}</p>
            </div>
          )}
        </section>
      )}

      {/* VWIs with confidence badges */}
      {result.vwis && result.vwis.length > 0 && (
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Vereiste VWI-procedures
          </h3>
          <div className="flex flex-wrap gap-2">
            {result.vwis.map((v) => (
              <div
                key={v.vwi_id}
                className="flex items-center gap-2 rounded-lg bg-zinc-50 px-3 py-2 dark:bg-zinc-800"
              >
                <span className="font-mono text-sm font-bold text-orange-600 dark:text-orange-400">
                  {v.vwi_id}
                </span>
                <ConfidenceBadge confidence={v.confidence} />
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Rationale */}
      {result.rationale && (
        <section>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Onderbouwing
          </h3>
          <p className="text-sm text-zinc-700 dark:text-zinc-300 whitespace-pre-wrap">
            {result.rationale}
          </p>
        </section>
      )}

      {/* Rule verdicts */}
      {result.rule_verdicts && result.rule_verdicts.length > 0 && (
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            BEI-BLS regelcontrole
          </h3>
          <div className="space-y-2">
            {result.rule_verdicts.map((v) => (
              <div
                key={v.rule_id}
                className="flex items-start gap-3 rounded-lg bg-zinc-50 px-3 py-2.5 dark:bg-zinc-800"
              >
                <StatusBadge ok={v.pass} labelOk="OK" labelFail="FAIL" />
                <div className="min-w-0">
                  <span className="font-mono text-xs font-bold text-zinc-600 dark:text-zinc-400">
                    {v.rule_id}
                  </span>
                  <p className="mt-0.5 text-xs text-zinc-600 dark:text-zinc-400">
                    {v.reason}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Review findings (LLM-as-judge) */}
      {result.review_findings && result.review_findings.length > 0 && (
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Reviewer beoordeling
          </h3>
          <div className="space-y-2">
            {result.review_findings.map((f) => (
              <div
                key={f.criterion}
                className="flex items-start gap-3 rounded-lg bg-zinc-50 px-3 py-2.5 dark:bg-zinc-800"
              >
                <StatusBadge ok={f.verdict === "pass"} labelOk="OK" labelFail="FAIL" />
                <div className="min-w-0">
                  <span className="text-xs font-bold text-zinc-600 dark:text-zinc-400">
                    {f.criterion.replace(/_/g, " ")}
                  </span>
                  <p className="mt-0.5 text-xs text-zinc-600 dark:text-zinc-400">
                    {f.reason}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Citations */}
      {result.citations && (
        <section>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Bronverwijzingen
          </h3>
          <div className="space-y-1">
            {result.citations.vwi_refs && result.citations.vwi_refs.length > 0 && (
              <div>
                <span className="text-xs font-medium text-zinc-500">VWI:</span>
                <ul className="list-disc list-inside">
                  {result.citations.vwi_refs.map((c, i) => (
                    <li key={i} className="text-xs text-zinc-500 dark:text-zinc-400">{c}</li>
                  ))}
                </ul>
              </div>
            )}
            {result.citations.raamopdracht_scope_excerpts && result.citations.raamopdracht_scope_excerpts.length > 0 && (
              <div>
                <span className="text-xs font-medium text-zinc-500">Raamopdracht scope:</span>
                <ul className="list-disc list-inside">
                  {result.citations.raamopdracht_scope_excerpts.map((c, i) => (
                    <li key={i} className="text-xs text-zinc-500 dark:text-zinc-400 italic">&ldquo;{c}&rdquo;</li>
                  ))}
                </ul>
              </div>
            )}
            {result.citations.bei_rule_refs && result.citations.bei_rule_refs.length > 0 && (
              <div>
                <span className="text-xs font-medium text-zinc-500">BEI regels:</span>
                <ul className="list-disc list-inside">
                  {result.citations.bei_rule_refs.map((c, i) => (
                    <li key={i} className="text-xs text-zinc-500 dark:text-zinc-400">{c}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </section>
      )}

      {/* Raw fallback */}
      {result.raw && (
        <pre className="overflow-x-auto rounded-xl bg-zinc-100 p-4 text-xs text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300 whitespace-pre-wrap">
          {result.raw}
        </pre>
      )}

      <p className="text-xs text-zinc-400 dark:text-zinc-600 border-t border-zinc-100 dark:border-zinc-800 pt-3">
        Dit systeem autoriseert geen werkzaamheden. Aanbeveling ter beoordeling door de dispatcher. De LMRA blijft de verantwoordelijkheid van de uitvoerend monteur.
      </p>
    </div>
  );
}
