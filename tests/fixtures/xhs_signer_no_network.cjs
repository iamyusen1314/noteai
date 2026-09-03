"use strict";

const Module = require("node:module");

const blocked = new Set([
  "dgram",
  "dns",
  "http",
  "http2",
  "https",
  "net",
  "tls",
  "node:dgram",
  "node:dns",
  "node:http",
  "node:http2",
  "node:https",
  "node:net",
  "node:tls",
]);
const originalLoad = Module._load;
Module._load = function denyNetworkModule(request, parent, isMain) {
  if (blocked.has(request)) throw new Error("network module disabled");
  return originalLoad.call(this, request, parent, isMain);
};

global.fetch = function denyFetch() {
  throw new Error("network disabled");
};
