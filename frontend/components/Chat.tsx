"use client";

import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
  useLocalRuntime,
  type ChatModelAdapter,
  type ReasoningMessagePartProps,
} from "@assistant-ui/react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Markdown } from "@/components/Markdown";
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

const SUGGESTIONS = [
  "How many loci are absent from every catalog?",
  "Show me novel VNTRs in disease genes",
  "Which motif class has the highest novel fraction, and why?",
  "What's in the merged SV VCF, and where does it keep the insertion?",
];

function TextPart({ text }: { text: string }) {
  return <Markdown>{text}</Markdown>;
}

function Chevron() {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden
      className="h-3 w-3 shrink-0 transition-transform group-open:rotate-90"
    >
      <path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" strokeWidth="2.5" />
    </svg>
  );
}

/**
 * Reasoning has two lives.
 *
 * While the model is still thinking it is the only thing to look at, so it
 * streams in place. The moment the answer starts it stops being the point, and
 * collapses to a chevron that only names itself on hover — the answer is what
 * you came for, and a permanent "Reasoning" box above every reply competes with
 * it for the top of the pane.
 */
function ReasoningPart({ text, status }: ReasoningMessagePartProps) {
  // Two conditions, because either one alone can get stuck. The part status
  // goes complete when the answer starts, which is the collapse we want; but a
  // turn that ends without ever producing text leaves reasoning as the last
  // part, and it would stay expanded for good. Once the message is done, it
  // collapses no matter what the part says.
  const settled = useAuiState((state) => state.message.status?.type !== "running");
  const live = status.type === "running" && !settled;
  const trail = useRef<HTMLDivElement>(null);

  // Follow the tail while it streams, so the newest sentence stays in view
  // without the capped box growing the whole thread.
  useEffect(() => {
    if (live && trail.current) {
      trail.current.scrollTop = trail.current.scrollHeight;
    }
  }, [text, live]);

  if (!text.trim()) return null;

  if (live) {
    return (
      <div className="rounded-md border border-hairline bg-surface px-2 py-1.5">
        <p className="animate-pulse text-[10px] uppercase tracking-wide text-ink-muted">
          Reasoning
        </p>
        <div
          ref={trail}
          className="scroll-quiet mt-1 max-h-40 overflow-y-auto whitespace-pre-wrap text-[11px] leading-relaxed text-ink-secondary"
        >
          {text}
        </div>
      </div>
    );
  }

  return (
    <details className="group">
      <summary className="flex cursor-pointer list-none items-center gap-1 text-[10px] text-ink-muted opacity-40 transition-opacity hover:opacity-100 group-open:opacity-100">
        <Chevron />
        <span className="uppercase tracking-wide opacity-0 transition-opacity group-hover:opacity-100 group-open:opacity-100">
          Reasoning
        </span>
      </summary>
      <div className="mt-1 whitespace-pre-wrap text-[11px] leading-relaxed text-ink-secondary">
        {text}
      </div>
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
                charts read, and can move the view for you.
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
              <div className="space-y-1.5">
                {SUGGESTIONS.map((prompt) => (
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
