"use client";

import { useState } from "react";
import { FileText, Trash2, Upload } from "lucide-react";

import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { Attachment } from "@/types/workflow";

const KIND_LABELS: Record<string, string> = {
  brd: "BRD",
  pdd: "PDD",
  sdd: "SDD",
  other: "Doc",
};

export function AttachmentsPanel({
  workflowId,
  initialAttachments,
}: {
  workflowId: string;
  initialAttachments: Attachment[];
}) {
  const [attachments, setAttachments] = useState(initialAttachments);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function upload(file: File) {
    setBusy("upload");
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const attachment = await api.addAttachment(workflowId, formData);
      setAttachments([attachment, ...attachments]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(null);
    }
  }

  async function remove(attachmentId: string) {
    setBusy(attachmentId);
    setError(null);
    try {
      await api.deleteAttachment(attachmentId);
      setAttachments(attachments.filter((item) => item.id !== attachmentId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="grid gap-4">
      <p className="text-sm text-slate-600">
        Requirement documents are matched against this workflow alongside the source prompt. Attaching
        one changes the prompt alignment score, so re-run the evaluation after uploading.
      </p>

      <label className="flex w-fit cursor-pointer items-center gap-2 border border-line px-4 py-2 text-sm hover:border-slate-400">
        <Upload size={16} />
        {busy === "upload" ? "Uploading..." : "Attach requirement document"}
        <input
          type="file"
          accept=".md,.markdown,.txt,text/markdown,text/plain"
          className="sr-only"
          onChange={(event) => {
            const file = event.target.files?.item(0);
            if (file) void upload(file);
            event.target.value = "";
          }}
        />
      </label>
      <span className="-mt-2 text-xs text-slate-500">Markdown or plain text, optional.</span>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {attachments.length === 0 ? (
        <p className="text-sm text-slate-500">
          No requirement documents attached. Alignment is scored from the source prompt alone.
        </p>
      ) : (
        <ul className="grid gap-2">
          {attachments.map((attachment) => (
            <li
              key={attachment.id}
              className="flex items-center justify-between gap-4 border border-line px-4 py-3"
            >
              <div className="flex items-center gap-3">
                <FileText size={18} className="text-slate-500" />
                <div>
                  <p className="text-sm font-medium">
                    <span className="mr-2 border border-line px-1.5 py-0.5 text-xs uppercase text-slate-600">
                      {KIND_LABELS[attachment.kind] ?? "Doc"}
                    </span>
                    {attachment.filename}
                  </p>
                  <p className="text-xs text-slate-500">
                    {attachment.clause_count} requirement{attachment.clause_count === 1 ? "" : "s"} ·{" "}
                    {Math.round(attachment.size_bytes / 1024)} KB · {formatDate(attachment.created_at)}
                  </p>
                </div>
              </div>
              <button
                type="button"
                className="flex items-center gap-1 border border-line px-3 py-1.5 text-xs hover:border-slate-400 disabled:opacity-50"
                disabled={busy === attachment.id}
                onClick={() => void remove(attachment.id)}
              >
                <Trash2 size={14} />
                {busy === attachment.id ? "Removing..." : "Remove"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
