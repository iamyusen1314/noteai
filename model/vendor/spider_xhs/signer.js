"use strict";

// Credentials and signing input arrive only on stdin.  This wrapper never
// reads cookies from argv or environment and writes only the fixed signature
// response fields to stdout.
const fs = require("fs");
const vm = require("vm");

function fail() {
  process.exitCode = 1;
}

try {
  const inputBytes = fs.readFileSync(0);
  if (inputBytes.length > 1024 * 1024) throw new Error("input too large");
  const input = JSON.parse(inputBytes.toString("utf8"));
  if (!input || typeof input !== "object") throw new Error("invalid input");
  if (!new Set(["GET", "POST"]).has(input.method)) throw new Error("invalid method");
  const endpoint = String(input.api || "").split("?", 1)[0];
  const allowed = new Set([
    "POST /api/sns/web/v1/homefeed",
    "GET /api/sns/web/v1/search/recommend",
    "POST /api/sns/web/v1/search/notes",
    "POST /api/sns/web/v1/feed",
  ]);
  if (!allowed.has(`${input.method} ${endpoint}`)) throw new Error("invalid api");
  if (typeof input.a1 !== "string" || !input.a1) throw new Error("missing a1");

  const main = require("./xhs_main_260411.js");
  const signed = main.get_request_headers_params(
    input.api,
    input.data || "",
    input.a1,
    input.method,
  );
  const output = {
    xs: String(signed.xs || ""),
    xt: String(signed.xt || ""),
    xs_common: String(signed.xs_common || ""),
  };
  if (input.needs_rap === true) {
    // Keep the pinned upstream asset byte-identical and evaluate it only in
    // this short-lived signer process.
    global.require = require;
    vm.runInThisContext(fs.readFileSync("./xhs_rap.js", "utf8"), {
      filename: "xhs_rap.js",
    });
    if (typeof generate_x_rap_param !== "function") throw new Error("rap unavailable");
    output.x_rap_param = String(generate_x_rap_param(input.api, input.data || "") || "");
  }
  if (!output.xs || !output.xt || !output.xs_common) throw new Error("sign failed");
  if (input.needs_rap === true && !output.x_rap_param) throw new Error("rap failed");
  process.stdout.write(JSON.stringify(output));
} catch (_error) {
  fail();
}
