import { describe, expect, it } from "vitest";

import { formatSourceFormat, scoreTone } from "@/lib/format";

describe("format helpers", () => {
  it("formats source formats for display", () => {
    expect(formatSourceFormat("generic_json")).toBe("GENERIC JSON");
  });

  it("assigns score tones", () => {
    expect(scoreTone(92)).toContain("ok");
    expect(scoreTone(70)).toContain("warn");
    expect(scoreTone(20)).toContain("danger");
  });
});
