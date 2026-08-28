"use client";

import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useLocalRuntime,
  type ChatModelAdapter,
} from "@assistant-ui/react";
import { useMemo, useState } from "react";

import { streamChat } from "@/lib/api";
import type { ViewFilters } from "@/lib/types";
import { useView } from "@/lib/viewStore";

/**
 * The chat pane.
 *
 * The important part is not that there is a chatbot — it is that the agent's
 * `set_view` tool writes to the same filter state the chips do. Ask for
 * something and the catalog moves; the answer and the view stay in sync instead
 * of being two disconnected panels.
 */

interface ToolEvent {
  name: string;
  args: Record<string, unknown>;
}

/**
 * The empty state, and the only place the agent's range is written down for the
 * person using it. A text box advertises nothing, so somebody who has not read
 * `app/tools.py` will type one cohort-level question and conclude that is all
 * there is. The groups here are the tool surface: query the registered tables,
 * move the view, cross to the disease locus reference, and account for what data
 * is loaded — including files they dropped in themselves.
 *
 * Every prompt is answerable against the HPRC callset this interface ships
 * pointed at. `chr4:39,348,3xx` is the CANVAS/RFC1 site, where five of the six
 * candidates carry a motif hg38 does not have there — which is the finding, not
 * a coordinate picked to have something in it.
 */
const SUGGESTIONS: { label: string; prompts: string[] }[] = [
  {
    label: "Ask the callset",
    prompts: [
      "How many loci are absent from every catalog?",
      "Which motif class has the highest novel fraction, and why?",
      "Where do UCSC and TRExplorer disagree about novelty?",
      "Which sample carries the most novel loci?",
    ],
  },
  {
    label: "Move the view",
    prompts: [
      "Show me novel VNTRs in disease genes",
      "Biggest insertions first, and open the top one",
      "Zoom to chr4:39,348,300-39,348,600",
    ],
  },
  {
    label: "Disease loci",
    prompts: [
      "Which disease loci is hg38 missing the pathogenic motif for?",
      "Open CANVAS_RFC1 — did we find anything there?",
    ],
  },
  {
    label: "The data itself",
    prompts: [
      "What tables are you querying, and is any of it synthetic?",
      "What have I uploaded, and can you query it?",
    ],
  },
];

function TextPart({ text }: { text: string }) {
  return <p className="whitespace-pre-wrap leading-relaxed">{text}</p>;
}

function ReasoningPart({ text }: { text: string }) {
  if (!text.trim()) return null;
  return (
    <details className="group rounded-md border border-hairline bg-surface px-2 py-1.5">
      <summary className="cursor-pointer list-none text-[11px] text-ink-muted">
        Reasoning
      </summary>
      <p className="mt-1.5 whitespace-pre-wrap text-[11px] leading-relaxed text-ink-secondary">
        {text}
      </p>
    </details>
  );
}

export function Chat({ agentEnabled }: { agentEnabled: boolean }) {
  const { patch } = useView();
  const [tools, setTools] = useState<ToolEvent[]>([]);

  const adapter = useMemo<ChatModelAdapter>(
    () => ({
      async *run({ messages, abortSignal }) {
        const history = messages
          .map((message) => ({
            role: message.role === "assistant" ? ("assistant" as const) : ("user" as const),
            content: message.content
              .map((part) => (part.type === "text" ? part.text : ""))
              .join(""),
          }))
          .filter((message) => message.content.length > 0);

        let text = "";
        let reasoning = "";
        let failure: string | null = null;
        const queue: string[] = [];

        setTools([]);

        // The SSE reader pushes into `queue`; the generator drains it so each
        // yield reflects everything received so far.
        const pump = streamChat(
          history,
          (event) => {
            switch (event.type) {
              case "text":
                text += event.delta;
                queue.push("tick");
                break;
              case "thinking":
                reasoning += event.delta;
                queue.push("tick");
                break;
              case "tool":
                setTools((current) => [...current, { name: event.name, args: event.args }]);
                break;
              case "view":
                patch(event.filters as ViewFilters, "agent");
                break;
              case "error":
                failure = event.message;
                queue.push("tick");
                break;
              case "done":
                break;
            }
          },
          abortSignal,
        );

        const build = () => {
          const content: { type: "reasoning" | "text"; text: string }[] = [];
          if (reasoning) content.push({ type: "reasoning", text: reasoning });
          if (text || failure) {
            content.push({ type: "text", text: failure ? `⚠ ${failure}` : text });
          }
          return { content: content.length ? content : [{ type: "text" as const, text: "" }] };
        };

        let settled = false;
        pump
          .catch((error: Error) => {
            failure = error.message;
          })
          .finally(() => {
            settled = true;
          });

        // Poll the accumulators until the stream resolves.
        while (!settled) {
          await new Promise((resolve) => setTimeout(resolve, 40));
          if (queue.length) {
            queue.length = 0;
            yield build();
          }
        }
        yield build();
      },
    }),
    [patch],
  );

  const runtime = useLocalRuntime(adapter);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root className="flex min-h-0 flex-1 flex-col">
        <ThreadPrimitive.Viewport className="scroll-quiet min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3">
          <ThreadPrimitive.Empty>
            <div className="space-y-3">
              <p className="text-xs leading-relaxed text-ink-secondary">
                Ask about the callset. The assistant queries the same data the
                charts read, moves the view for you, and knows which tables — and
                which of your uploads — are loaded.
              </p>
              {!agentEnabled && (
                <p
                  className="rounded-md px-2.5 py-2 text-[11px] leading-relaxed"
                  style={{ background: "var(--novel-soft)", color: "var(--novel)" }}
                >
                  No model credential configured. Copy{" "}
                  <span className="tabular">backend/.env.example</span> to{" "}
                  <span className="tabular">backend/.env</span> and set a key to enable chat.
                </p>
              )}
              <div className="space-y-2.5">
                {SUGGESTIONS.map((group) => (
                  <div key={group.label} className="space-y-1.5">
                    <p className="text-[10px] uppercase tracking-wide text-ink-muted">
                      {group.label}
                    </p>
                    {group.prompts.map((prompt) => (
                      <ThreadPrimitive.Suggestion
                        key={prompt}
                        prompt={prompt}
                        method="replace"
                        autoSend
                        className="block w-full rounded-md border border-hairline px-2.5 py-1.5 text-left text-xs text-ink-secondary transition-colors hover:border-baseline hover:text-ink"
                      >
                        {prompt}
                      </ThreadPrimitive.Suggestion>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          </ThreadPrimitive.Empty>

          <ThreadPrimitive.Messages
            components={{
              UserMessage: () => (
                <MessagePrimitive.Root className="flex justify-end">
                  <div className="max-w-[85%] rounded-lg rounded-br-sm bg-surface-raised px-2.5 py-1.5 text-xs text-ink">
                    <MessagePrimitive.Parts components={{ Text: TextPart }} />
                  </div>
                </MessagePrimitive.Root>
              ),
              AssistantMessage: () => (
                <MessagePrimitive.Root className="space-y-1.5 text-xs text-ink">
                  <MessagePrimitive.Parts
                    components={{ Text: TextPart, Reasoning: ReasoningPart }}
                  />
                </MessagePrimitive.Root>
              ),
            }}
          />
        </ThreadPrimitive.Viewport>

        {tools.length > 0 && (
          <div className="border-t border-hairline px-3 py-2">
            <p className="mb-1 text-[10px] uppercase tracking-wide text-ink-muted">
              Agent actions
            </p>
            <ul className="space-y-0.5">
              {tools.slice(-4).map((tool, index) => (
                <li key={index} className="tabular truncate text-[11px] text-ink-secondary">
                  <span style={{ color: "var(--motif-1)" }}>{tool.name}</span>
                  {tool.name === "run_sql" ? (
                    <span className="text-ink-muted"> · {String(tool.args.query ?? "").slice(0, 60)}…</span>
                  ) : (
                    <span className="text-ink-muted"> · {JSON.stringify(tool.args).slice(0, 60)}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        <ComposerPrimitive.Root className="flex items-end gap-2 border-t border-hairline p-2.5">
          <ComposerPrimitive.Input
            rows={1}
            autoFocus
            placeholder="Ask about these loci…"
            className="max-h-32 min-h-[2.25rem] flex-1 resize-none rounded-md border border-hairline bg-surface px-2.5 py-2 text-xs text-ink outline-none placeholder:text-ink-muted focus:border-baseline"
          />
          <ComposerPrimitive.Send
            className="shrink-0 rounded-md px-3 py-2 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
            style={{ background: "var(--motif-1)" }}
          >
            Send
          </ComposerPrimitive.Send>
        </ComposerPrimitive.Root>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}
