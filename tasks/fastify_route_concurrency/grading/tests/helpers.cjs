'use strict'

const fastify = require(process.env.FASTIFY_REPO)

// forceCloseConnections keeps `app.close()` from waiting on a client that an
// implementation left hanging (an unreleased slot, an unfinished stream), so a
// failing test reports its assertion instead of stalling the whole suite.
function Fastify (opts = {}) {
  return fastify({ forceCloseConnections: true, ...opts })
}

function deferred () {
  let release
  const promise = new Promise(resolve => {
    release = resolve
  })
  return { promise, resolve: release }
}

function delay (milliseconds) {
  return new Promise(resolve => setTimeout(resolve, milliseconds))
}

async function waitFor (predicate, milliseconds = 1000) {
  const deadline = Date.now() + milliseconds
  while (!predicate()) {
    if (Date.now() >= deadline) throw new Error('condition timed out')
    await delay(2)
  }
}

// Await a request that a correct implementation answers at once (a 503
// rejection). If it is still pending after `milliseconds`, fail with a
// message instead of letting the test hang to its timeout.
function expectPrompt (promise, milliseconds, what) {
  let timer
  const deadline = new Promise((resolve, reject) => {
    timer = setTimeout(() => reject(new Error(`${what} still pending after ${milliseconds} ms (request was admitted or queued instead of being rejected)`)), milliseconds)
  })
  return Promise.race([promise, deadline]).finally(() => clearTimeout(timer))
}

module.exports = { Fastify, deferred, delay, waitFor, expectPrompt }
