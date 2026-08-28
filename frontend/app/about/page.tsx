import type { Metadata } from "next";

import { Workspace } from "@/components/Workspace";

export const metadata: Metadata = {
  title: "About · inTRuder",
  description: "What inTRuder is, and the team that built it.",
};

export default function AboutPage() {
  return <Workspace initial={{ page: "about" }} />;
}
