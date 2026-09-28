import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { buildReplayModel, replayDuration, stageAt } from "./replayData.ts";

test("saved NAVER run becomes a complete replay without inventing counts", () => {
  const snapshot = JSON.parse(readFileSync(new URL("../../../public/demo/naver-2025.json", import.meta.url), "utf8"));
  const model = buildReplayModel(snapshot);
  assert.equal(model.stages.length, 9);
  assert.equal(model.stages[1].count, snapshot.coverage.pages_processed);
  assert.equal(model.stages[2].count, snapshot.coverage.claims_discovered);
  assert.equal(model.stages[6].count, snapshot.coverage.claims_decided);
  assert.equal(model.paidCalls, snapshot.run.r72_paid_calls);
  assert.equal(model.costUsd, snapshot.run.r72_cost_usd);
  assert.equal(model.parseSeconds, snapshot.run.r72_elapsed_seconds.parse_extraction);
  assert.equal(model.taggingSeconds, snapshot.run.r72_elapsed_seconds.tagging);
  assert.equal(replayDuration(model.stages), 37700);
  assert.equal(stageAt(model.stages, replayDuration(model.stages)).index, 9);
});

test("missing optional data stays unknown and added demo pass data is used", () => {
  const model = buildReplayModel({ coverage: { claims_decided: 12 }, demo_pass: { claims_decided: 12 } });
  assert.equal(model.pagesProcessed, null);
  assert.equal(model.paidCalls, null);
  assert.deepEqual(model.demoPass, { label: "시연 통과", count: 12 });
});
