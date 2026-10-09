// Synthetic render checks; does not perform external searches or contact APIs.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { Script } from "node:vm";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const require = createRequire(import.meta.url);
const source = readFileSync(
  new URL("../src/EvidencePanel.tsx", import.meta.url),
  "utf8",
);
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    jsx: ts.JsxEmit.ReactJSX,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
const mod = { exports: {} };
new Script(
  `(function(require,module,exports){${compiled}\n})`,
).runInThisContext()(require, mod, mod.exports);
const { evidenceOrigin, EvidencePanel } = mod.exports;
const fixture = JSON.parse(
  readFileSync(
    new URL(
      "../../contracts/examples/request-record-demo.json",
      import.meta.url,
    ),
    "utf8",
  ),
).report;
assert.equal(evidenceOrigin(fixture.evidence).title, "모의 응답");
const paper = {
  ...fixture.evidence.cards[0],
  source_type: "paper",
  title: "Synthetic evidence display test",
  source_url: "https://example.invalid/source",
  excerpt: "Synthetic quotation for rendering checks.",
  applicability: "partial",
  matched_conditions: ["synthetic matching condition"],
  missing_conditions: ["synthetic missing condition"],
};
const review = {
  ...fixture.evidence,
  mock: false,
  status: "insufficient",
  cards: [paper],
  limitation: "사전 수집 문서 검토. Synthetic test only.",
};
assert.equal(evidenceOrigin(review).title, "사전 수집 논문");
assert.equal(
  evidenceOrigin({
    ...review,
    limitation: "실시간 Europe PMC 논문 검색·원문 수집. Synthetic test only.",
  }).title,
  "실시간 검색",
);
assert.equal(
  evidenceOrigin({
    ...review,
    status: "failed",
    limitation: "검토 실패",
    cards: [],
  }).title,
  "수집 방식 확인 불가",
);
const html = renderToStaticMarkup(
  React.createElement(EvidencePanel, {
    report: {
      ...fixture,
      verdict: "hold",
      reason_code: "EVIDENCE_INCOMPLETE",
      reason: "Synthetic server hold reason",
      evidence: review,
    },
  }),
);
for (const expected of [
  "사전 수집 논문",
  "Synthetic server hold reason",
  "EVIDENCE_INCOMPLETE",
  paper.excerpt,
  paper.matched_conditions[0],
  paper.missing_conditions[0],
  "https://example.invalid/source",
])
  assert.ok(html.includes(expected), `Missing evidence display: ${expected}`);
const malicious = renderToStaticMarkup(
  React.createElement(EvidencePanel, {
    report: {
      ...fixture,
      evidence: {
        ...review,
        cards: [{ ...paper, source_url: "javascript:alert(1)" }],
      },
    },
  }),
);
assert.ok(!malicious.includes('href="javascript:'));
assert.ok(
  renderToStaticMarkup(
    React.createElement(EvidencePanel, { report: null }),
  ).includes("근거 결과가 아직"),
);
console.log(
  "PASS: fixture, collected papers, live search, unknown origin, hold reason, source link, quotation, conditions, unsafe URL, empty state",
);
