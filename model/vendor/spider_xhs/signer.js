"use strict";

// Credentials and signing input arrive only on stdin.  This wrapper never
// reads cookies from argv or environment and writes only the fixed signature
// response fields to stdout.
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const quietConsole = {
  log() {},
  warn() {},
  error() {},
  info() {},
  debug() {},
};

function generateRapParam(api, data) {
  const rapRequire = (name) => {
    if (name !== "crypto") throw new Error("module not allowed");
    return require("node:crypto");
  };
  const context = vm.createContext({
    require: rapRequire,
    Buffer,
    URL,
    URLSearchParams,
    TextEncoder,
    TextDecoder,
    setTimeout,
    clearTimeout,
    console: quietConsole,
  });
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "xhs_rap.js"), "utf8"),
    context,
    { filename: "xhs_rap.js" },
  );
  if (typeof context.generate_x_rap_param !== "function") {
    throw new Error("rap unavailable");
  }
  return context.generate_x_rap_param(api, data || "");
}

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

  const originalConsole = global.console;
  global.console = quietConsole;
  let signed;
  try {
    const main = require("./xhs_main_260411.js");
    signed = main.get_request_headers_params(
      input.api,
      input.data || "",
      input.a1,
      input.method,
    );
  } finally {
    global.console = originalConsole;
  }
  const output = {
    xs: String(signed.xs || ""),
    xt: String(signed.xt || ""),
    xs_common: String(signed.xs_common || ""),
  };
  if (input.needs_rap === true) {
    // Keep the pinned upstream asset byte-identical and isolate it from the
    // main signer's process-global shims.
    output.x_rap_param = String(generateRapParam(input.api, input.data || "") || "");
  }
  if (!output.xs || !output.xt || !output.xs_common) throw new Error("sign failed");
  if (input.needs_rap === true && !output.x_rap_param) throw new Error("rap failed");
  process.stdout.write(JSON.stringify(output));
} catch (_error) {
  fail();
}
