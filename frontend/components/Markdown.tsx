"use client";

import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Markdown for assistant output.
 *
 * The agent writes prose with emphasis, lists and the occasional table of
 * numbers, so the raw text was never meant to be read literally — before this
 * the pane showed `**44.6%**` with the asterisks in it.
 *
 * Every element is mapped explicitly rather than left to browser defaults: the
 * chat pane runs at `text-xs` on the app's own ink/surface tokens, and unstyled
 * `<h2>`/`<ul>`/`<table>` would each arrive at their own scale and break it.
 */

const COMPONENTS: Components = {
  p: ({ children }) => <p className="leading-relaxed [&:not(:first-child)]:mt-2">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-ink">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  a: ({ children, href }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="underline underline-offset-2"
      style={{ color: "var(--motif-1)" }}
    >
      {children}
    </a>
  ),
  ul: ({ children }) => (
    <ul className="mt-2 list-disc space-y-0.5 pl-4 marker:text-ink-muted">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="mt-2 list-decimal space-y-0.5 pl-4 marker:text-ink-muted">{children}</ol>
  ),
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  // Headings in a pane this narrow are separators, not a type hierarchy — one
  // weight for all levels, so an h1 the model emits cannot tower over the text.
  h1: ({ children }) => <p className="mt-2.5 font-semibold text-ink">{children}</p>,
  h2: ({ children }) => <p className="mt-2.5 font-semibold text-ink">{children}</p>,
  h3: ({ children }) => <p className="mt-2.5 font-semibold text-ink">{children}</p>,
  h4: ({ children }) => <p className="mt-2.5 font-semibold text-ink">{children}</p>,
  blockquote: ({ children }) => (
    <blockquote className="mt-2 border-l-2 border-hairline pl-2.5 text-ink-secondary">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-2.5 border-hairline" />,
  code: ({ className, children }) => {
    // react-markdown gives fenced blocks a `language-*` class and inline code
    // none. Only the fenced ones get a scroll container.
    const fenced = /language-/.test(className ?? "");
    if (!fenced) {
      return (
        <code className="tabular rounded bg-surface-raised px-1 py-0.5 text-[11px]">
          {children}
        </code>
      );
    }
    return <code className="tabular block text-[11px] leading-relaxed">{children}</code>;
  },
  pre: ({ children }) => (
    <pre className="scroll-quiet mt-2 overflow-x-auto rounded-md border border-hairline bg-surface p-2">
      {children}
    </pre>
  ),
  // A table of counts is the one thing that must not wrap, so it scrolls.
  table: ({ children }) => (
    <div className="scroll-quiet mt-2 overflow-x-auto">
      <table className="w-full border-collapse text-[11px]">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border-b border-hairline px-1.5 py-1 text-left font-medium text-ink-secondary">
      {children}
    </th>
  ),
  td: ({ children }) => <td className="tabular border-b border-hairline px-1.5 py-1">{children}</td>,
};

export function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
      {children}
    </ReactMarkdown>
  );
}
