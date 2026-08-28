import type { Metadata } from "next";

import { Workspace } from "@/components/Workspace";

export const metadata: Metadata = {
  title: "Hackathon Presentation · inTRuder",
  description:
    "What we built and what it found: the problem, the pipeline, the results, and the interface that browses them.",
};

export default function PresentationPage() {
  return <Workspace initial={{ page: "presentation" }} />;
}
