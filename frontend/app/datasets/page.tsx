import type { Metadata } from "next";

import { Workspace } from "@/components/Workspace";

export const metadata: Metadata = {
  title: "Datasets · novelTRs",
  description:
    "The tables this deployment can read, the files uploaded to it, and which of them drive the views.",
};

export default function DatasetsPage() {
  return <Workspace initial={{ page: "datasets" }} />;
}
