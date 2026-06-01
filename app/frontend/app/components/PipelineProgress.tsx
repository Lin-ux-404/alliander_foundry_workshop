"use client";

import { useEffect, useState } from "react";

interface Step {
  agent: string;
  summary: string;
  status: "running" | "done";
  timestamp: number;
  streamText?: string;
}

const AGENT_LABELS: Record<string, string> = {
  intent_classifier: "Intent Classificatie",
  procedure_retriever: "Procedure Retriever",
  dispatch_matcher: "Dispatch Matcher",
  rule_checker: "BEI-BLS Regelcontrole",
  dispatch_reviewer: "Dispatch Reviewer",
  qa_assistant: "Q&A Assistent",
  pipeline: "Pipeline",
};

const AGENT_ICONS: Record<string, string> = {
  intent_classifier: "🔍",
  procedure_retriever: "📚",
  dispatch_matcher: "🎯",
  rule_checker: "✅",
  dispatch_reviewer: "⚖️",
  qa_assistant: "💬",
  pipeline: "✨",
};

interface Props {
  steps: Step[];
}

export type { Step };

export default function PipelineProgress({ steps }: Props) {
  if (steps.length === 0) return null;

  return (
    <div className="space-y-1.5">
      {steps.map((step, i) => (
        <div
          key={`${step.agent}-${i}`}
          className="flex items-start gap-3 animate-in fade-in slide-in-from-bottom-2 duration-300"
          style={{ animationDelay: `${i * 50}ms` }}
        >
          {/* Timeline dot + line */}
          <div className="flex flex-col items-center pt-1">
            <div
              className={`h-2.5 w-2.5 rounded-full ${
                step.status === "running"
                  ? "bg-orange-400 animate-pulse"
                  : "bg-green-500"
              }`}
            />
            {i < steps.length - 1 && (
              <div className="w-px flex-1 bg-zinc-200 dark:bg-zinc-700 min-h-[16px]" />
            )}
          </div>

          {/* Content */}
          <div className="min-w-0 flex-1 pb-1">
            <div className="flex items-center gap-2">
              <span className="text-sm">
                {AGENT_ICONS[step.agent] || "🔧"}
              </span>
              <span className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                {AGENT_LABELS[step.agent] || step.agent}
              </span>
              {step.status === "running" && (
                <span className="inline-flex items-center gap-1 text-xs text-orange-500">
                  <span className="h-1.5 w-1.5 animate-ping rounded-full bg-orange-400" />
                  bezig...
                </span>
              )}
            </div>
            {step.status === "running" && step.streamText ? (
              <pre className="text-xs text-zinc-600 dark:text-zinc-400 mt-1 leading-relaxed whitespace-pre-wrap break-words max-h-40 overflow-y-auto font-mono bg-zinc-50 dark:bg-zinc-900 rounded p-2">
                {step.streamText}
                <span className="animate-pulse">▍</span>
              </pre>
            ) : (
              <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5 leading-relaxed">
                {step.summary}
              </p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
