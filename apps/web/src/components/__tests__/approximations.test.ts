import { describe, expect, it } from "vitest";

import type { TestRunSummary } from "@/types/workflow";

type Run = TestRunSummary["runs"][number];

/**
 * A run's warnings say where it approximated rather than measured. They are the difference
 * between "this workflow passed" and "this workflow passed, and four of its nodes were never
 * really exercised", so they must survive the trip from the API to the panel untouched.
 */
function approximations(run: Pick<Run, "execution_trace">): string[] {
  return run.execution_trace.warnings ?? [];
}

describe("run approximations", () => {
  it("are read from the execution trace", () => {
    const run = {
      execution_trace: {
        warnings: ["Node 'x' runs javascript; it was not executed."],
      },
    } as Pick<Run, "execution_trace">;
    expect(approximations(run)).toHaveLength(1);
  });

  it("are absent rather than undefined for a run with nothing to flag", () => {
    const run = { execution_trace: {} } as Pick<Run, "execution_trace">;
    expect(approximations(run)).toEqual([]);
  });

  it("are separate from failures, because nothing went wrong", () => {
    const run = {
      execution_trace: { failures: ["boom"], warnings: ["approval was auto-answered"] },
    } as Pick<Run, "execution_trace">;
    expect(approximations(run)).toEqual(["approval was auto-answered"]);
  });
});
