import type { Metadata } from "next";

import { Workspace } from "@/components/Workspace";

export const metadata: Metadata = {
  title: "Disease loci · novelTRs",
  description:
    "Tandem repeats known to cause human disease, curated by STRchive, and this cohort's candidates screened against them.",
};

export default function StrchivePage() {
  return <Workspace initial={{ page: "strchive" }} />;
}
