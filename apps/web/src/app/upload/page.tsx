"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { FileUp } from "lucide-react";

import { api } from "@/lib/api";

export default function UploadPage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [sourceType, setSourceType] = useState("human");
  const [sourcePrompt, setSourcePrompt] = useState("");
  const [requirementDoc, setRequirementDoc] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);

  async function submit() {
    if (!file) {
      setError("Choose a BPMN, XML, or JSON workflow file.");
      return;
    }
    const formData = new FormData();
    formData.append("file", file);
    formData.append("source_type", sourceType);
    if (sourceType === "ai_generated" && sourcePrompt.trim()) formData.append("source_prompt", sourcePrompt.trim());
    setIsUploading(true);
    setError(null);
    try {
      const workflow = await api.uploadWorkflow(formData);
      if (requirementDoc) {
        // Attached after the workflow exists, since the attachment hangs off its id.
        const documentData = new FormData();
        documentData.append("file", requirementDoc);
        await api.addAttachment(workflow.id, documentData);
      }
      router.push(`/workflows/${workflow.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <section className="px-5 py-7 lg:px-8">
      <h1 className="text-2xl font-semibold">Upload Workflow</h1>
      <div className="mt-7 grid max-w-3xl gap-5">
        <label
          className="flex min-h-52 cursor-pointer flex-col items-center justify-center border-2 border-dashed border-line bg-panel px-6 py-10 text-center hover:border-slate-400"
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            setFile(event.dataTransfer.files.item(0));
          }}
        >
          <FileUp size={34} className="text-slate-500" />
          <span className="mt-4 text-sm font-medium">{file ? file.name : "Drop a workflow file or browse"}</span>
          <span className="mt-1 text-xs text-slate-500">.bpmn, .xml, .json up to 5 MB</span>
          <input
            type="file"
            accept=".bpmn,.xml,.json,application/json,application/xml,text/xml"
            className="sr-only"
            onChange={(event) => setFile(event.target.files?.item(0) ?? null)}
          />
        </label>

        <div className="flex w-fit overflow-hidden border border-line">
          <button
            type="button"
            className={`px-4 py-2 text-sm ${sourceType === "human" ? "bg-ink text-white" : "bg-white text-slate-700"}`}
            onClick={() => setSourceType("human")}
          >
            Human created
          </button>
          <button
            type="button"
            className={`border-l border-line px-4 py-2 text-sm ${sourceType === "ai_generated" ? "bg-ink text-white" : "bg-white text-slate-700"}`}
            onClick={() => setSourceType("ai_generated")}
          >
            AI generated
          </button>
        </div>

        {sourceType === "ai_generated" && (
          <textarea
            value={sourcePrompt}
            onChange={(event) => setSourcePrompt(event.target.value)}
            rows={5}
            className="w-full border border-line px-3 py-2 text-sm outline-none focus:border-accent"
            placeholder="Original prompt"
          />
        )}

        <div className="border border-line p-4">
          <p className="text-sm font-medium">Requirement document (optional)</p>
          <p className="mt-1 text-xs text-slate-500">
            A BRD, PDD, or SDD describing what this workflow must do. Its requirements are matched
            against the workflow alongside the prompt, so attaching one changes the alignment score.
          </p>
          <label className="mt-3 flex w-fit cursor-pointer items-center gap-2 border border-line px-3 py-1.5 text-sm hover:border-slate-400">
            {requirementDoc ? requirementDoc.name : "Choose a .md or .txt file"}
            <input
              type="file"
              accept=".md,.markdown,.txt,text/markdown,text/plain"
              className="sr-only"
              onChange={(event) => setRequirementDoc(event.target.files?.item(0) ?? null)}
            />
          </label>
        </div>

        {error && <div className="border border-danger bg-red-50 p-3 text-sm text-danger">{error}</div>}
        <button
          type="button"
          disabled={isUploading}
          onClick={submit}
          className="w-fit rounded-md bg-ink px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isUploading ? "Uploading..." : "Upload and validate"}
        </button>
      </div>
    </section>
  );
}
