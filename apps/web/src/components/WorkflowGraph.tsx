"use client";

import { useMemo, useState } from "react";
import ReactFlow, { Background, Controls, type Edge as FlowEdge, type Node as FlowNode } from "reactflow";
import "reactflow/dist/style.css";
import { Bot, CheckCircle2, CircleStop, Database, GitBranch, Globe2, MousePointerClick, Play, Workflow } from "lucide-react";

import type { WorkflowDetail, WorkflowNode } from "@/types/workflow";

const colors: Record<string, string> = {
  trigger: "border-ok bg-emerald-50",
  action: "border-slate-400 bg-white",
  task: "border-slate-400 bg-white",
  condition: "border-warn bg-amber-50",
  llm: "border-accent bg-blue-50",
  human_approval: "border-indigo-500 bg-indigo-50",
  external_api: "border-cyan-600 bg-cyan-50",
  database: "border-violet-600 bg-violet-50",
  end: "border-danger bg-red-50"
};

export function WorkflowGraph({ workflow }: { workflow: WorkflowDetail }) {
  const [selectedNode, setSelectedNode] = useState<WorkflowNode | null>(null);
  const flow = useMemo(() => toFlow(workflow), [workflow]);

  return (
    <div className="grid min-h-[620px] gap-4 xl:grid-cols-[1fr_360px]">
      <div className="h-[620px] border border-line">
        <ReactFlow
          nodes={flow.nodes}
          edges={flow.edges}
          fitView
          onNodeClick={(_, node) => setSelectedNode(node.data.raw)}
        >
          <Background />
          <Controls />
        </ReactFlow>
      </div>
      <aside className="border border-line bg-panel p-4">
        {selectedNode ? (
          <div>
            <div className="text-xs uppercase text-slate-500">{selectedNode.type}</div>
            <h3 className="mt-1 text-lg font-semibold">{selectedNode.name}</h3>
            <pre className="mt-4 max-h-[510px] overflow-auto bg-white p-3 text-xs leading-relaxed">
              {JSON.stringify(selectedNode, null, 2)}
            </pre>
          </div>
        ) : (
          <div className="text-sm text-slate-600">Select a node to inspect configuration and preserved metadata.</div>
        )}
      </aside>
    </div>
  );
}

function toFlow(workflow: WorkflowDetail): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const nodeIndex = new Map(workflow.canonical.nodes.map((node, index) => [node.id, index]));
  return {
    nodes: workflow.canonical.nodes.map((node, index) => {
      const column = index % 4;
      const row = Math.floor(index / 4);
      return {
        id: node.id,
        position: { x: column * 240, y: row * 150 },
        data: { label: <NodeLabel node={node} />, raw: node },
        className: `border-2 ${colors[node.type] ?? "border-slate-300 bg-white"} rounded-md shadow-soft`,
        style: { width: 190 }
      };
    }),
    edges: workflow.canonical.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: edge.label ?? edge.condition ?? undefined,
      animated: Boolean(edge.condition),
      type: nodeIndex.has(edge.source) && nodeIndex.has(edge.target) ? "smoothstep" : "default"
    }))
  };
}

function NodeLabel({ node }: { node: WorkflowNode }) {
  return (
    <div className="flex items-start gap-2 p-2">
      {renderIcon(node.type)}
      <div className="min-w-0">
        <div className="truncate text-sm font-semibold">{node.name}</div>
        <div className="truncate text-xs text-slate-500">{node.provider ?? node.subtype ?? node.type}</div>
      </div>
    </div>
  );
}

function renderIcon(type: string) {
  const className = "mt-0.5 shrink-0";
  if (type === "trigger") return <Play size={17} className={className} />;
  if (type === "condition") return <GitBranch size={17} className={className} />;
  if (type === "llm") return <Bot size={17} className={className} />;
  if (type === "human_approval") return <MousePointerClick size={17} className={className} />;
  if (type === "external_api") return <Globe2 size={17} className={className} />;
  if (type === "database") return <Database size={17} className={className} />;
  if (type === "end") return <CircleStop size={17} className={className} />;
  if (type === "task" || type === "action") return <CheckCircle2 size={17} className={className} />;
  return <Workflow size={17} className={className} />;
}
