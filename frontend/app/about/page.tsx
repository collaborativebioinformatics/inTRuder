import type { Metadata } from "next";

import { Workspace } from "@/components/Workspace";

export const metadata: Metadata = {
  title: "About · novelTRs",
  description: "What novelTRs is, and the team that built it.",
};

export default function AboutPage() {
  return <Workspace initial={{ page: "about" }} />;
}
