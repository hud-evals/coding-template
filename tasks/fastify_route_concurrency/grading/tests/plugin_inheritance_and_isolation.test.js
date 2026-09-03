'use strict'

const { test } = require('node:test')
const assert = require('node:assert/strict')
const { Fastify, deferred, delay, waitFor, expectPrompt } = require('./helpers.cjs')

// ── plugin-level defaults and encapsulation ─────────────────────────────

test('plugin-level concurrency option automatically applies to all routes within plugin', async t => {
  const app = Fastify()
  const gate = deferred()
  t.after(() => gate.resolve())
  const started = []

  app.register(async function subPlugin (instance) {
    instance.get('/route-1', async () => {
      started.push('1')
      await gate.promise
      return '1'
    })

    instance.get('/route-2', async () => {
      started.push('2')
      return '2'
    })
  }, { prefix: '/sub', concurrency: { max: 1, queueLimit: 5 } })

  const req1 = app.inject('/sub/route-1')
  await waitFor(() => started.includes('1'), 500)

  const req2 = app.inject('/sub/route-1')
  await delay(20)

  assert.deepEqual(started, ['1'])

  gate.resolve()
  const [res1, res2] = await Promise.all([req1, req2])

  assert.equal(res1.statusCode, 200)
  assert.equal(res2.statusCode, 200)
  assert.deepEqual(started, ['1', '1'])
})

test('route-level concurrency overrides plugin-level concurrency', async t => {
  const app = Fastify()
  const gate = deferred()
  t.after(() => gate.resolve())
  const started = []

  app.register(async function subPlugin (instance) {
    instance.get('/inherited', async () => {
      started.push('inherited')
      await gate.promise
      return 'inherited'
    })

    // Explicitly overrides plugin default with max: 2
    instance.get('/overridden', { concurrency: { max: 2 } }, async () => {
      started.push('overridden')
      return 'overridden'
    })
  }, { prefix: '/sub', concurrency: { max: 1 } })

  const reqInherited = app.inject('/sub/inherited')
  await waitFor(() => started.includes('inherited'), 500)

  // /overridden has max: 2 independent route pool, should execute immediately
  const resOverridden = await app.inject('/sub/overridden')
  assert.equal(resOverridden.statusCode, 200)
  assert.deepEqual(started, ['inherited', 'overridden'])

  gate.resolve()
  await reqInherited
})

test('nested encapsulated plugins inherit parent concurrency unless re-configured', async t => {
  const app = Fastify()
  const gate = deferred()
  t.after(() => gate.resolve())
  const started = []

  app.register(async function parentPlugin (parent) {
    parent.register(async function childPlugin (child) {
      child.get('/nested', async () => {
        started.push('nested')
        await gate.promise
        return 'nested'
      })
    }, { prefix: '/child' })
  }, { prefix: '/parent', concurrency: { max: 1, queueLimit: 5 } })

  const req1 = app.inject('/parent/child/nested')
  await waitFor(() => started.includes('nested'), 500)

  const req2 = app.inject('/parent/child/nested')
  await delay(20)
  assert.deepEqual(started, ['nested'])

  gate.resolve()
  const [res1, res2] = await Promise.all([req1, req2])
  assert.equal(res1.statusCode, 200)
  assert.equal(res2.statusCode, 200)
})

test('3-tier deep encapsulation propagates concurrency with strict sibling isolation', async t => {
  const app = Fastify()
  const gateA = deferred()
  const gateB = deferred()
  t.after(() => {
    gateA.resolve()
    gateB.resolve()
  })
  const started = []

  // Branch A: max 2
  app.register(async function branchA (instanceA) {
    instanceA.register(async function subA (childA) {
      childA.register(async function deepA (grandA) {
        grandA.get('/deep-route', async () => {
          started.push('A')
          await gateA.promise
          return 'A'
        })
      }, { prefix: '/deep' })
    }, { prefix: '/sub' })
  }, { prefix: '/a', concurrency: { max: 2, queueLimit: 5 } })

  // Branch B: max 1, queueLimit 0
  app.register(async function branchB (instanceB) {
    instanceB.get('/route-b', async () => {
      started.push('B')
      await gateB.promise
      return 'B'
    })
  }, { prefix: '/b', concurrency: { max: 1, queueLimit: 0 } })

  const reqA1 = app.inject('/a/sub/deep/deep-route')
  const reqA2 = app.inject('/a/sub/deep/deep-route')
  await waitFor(() => started.filter(x => x === 'A').length === 2, 500)

  const reqB1 = app.inject('/b/route-b')
  await waitFor(() => started.includes('B'), 500)

  const reqB2 = await expectPrompt(app.inject('/b/route-b'), 1000, 'second request to a max:1 queueLimit:0 branch')
  assert.equal(reqB2.statusCode, 503)
  assert.equal(reqB2.json().code, 'FST_ERR_ROUTE_CONCURRENCY_QUEUE_FULL')

  gateA.resolve()
  gateB.resolve()
  const [resA1, resA2, resB1] = await Promise.all([reqA1, reqA2, reqB1])
  assert.equal(resA1.statusCode, 200)
  assert.equal(resA2.statusCode, 200)
  assert.equal(resB1.statusCode, 200)
})

test('sibling plugin registration does not pollute neighboring plugin concurrency options', async t => {
  const app = Fastify()
  const gateA = deferred()
  t.after(() => gateA.resolve())
  const started = []

  // Parent plugin with default concurrency max: 5
  app.register(async function parentPlugin (parent) {
    // Sibling 1 overrides concurrency to max: 1, no queue. A short queueTimeout
    // keeps this test from hanging if an implementation wrongly queues.
    parent.register(async function sibling1 (s1) {
      s1.get('/route-1', async () => {
        started.push('S1')
        await gateA.promise
        return 's1'
      })
    }, { prefix: '/s1', concurrency: { max: 1, queueLimit: 0, queueTimeout: 300 } })

    // Sibling 2 does not specify concurrency, must inherit parent max: 5 (NOT sibling1 max: 1)
    parent.register(async function sibling2 (s2) {
      s2.get('/route-2', async () => {
        started.push('S2')
        return 's2'
      })
    }, { prefix: '/s2' })
  }, { prefix: '/parent', concurrency: { max: 5 } })

  const reqS1_1 = app.inject('/parent/s1/route-1')
  await waitFor(() => started.includes('S1'), 500)

  // Sibling 1 queue is 0, so second request to S1 must be rejected with 503
  const resS1_2 = await expectPrompt(app.inject('/parent/s1/route-1'), 1000, 'second request to sibling 1 (max:1, queueLimit:0)')
  assert.equal(resS1_2.statusCode, 503)
  assert.equal(resS1_2.json().code, 'FST_ERR_ROUTE_CONCURRENCY_QUEUE_FULL')

  // Sibling 2 must inherit parent max: 5 and admit work immediately
  const resS2 = await app.inject('/parent/s2/route-2')
  assert.equal(resS2.statusCode, 200)

  gateA.resolve()
  await reqS1_1
})

// ── per-route state and the request-side view ───────────────────────────

test('different HTTP methods on the same path maintain isolated concurrency pools', async t => {
  const app = Fastify()
  const gateGet = deferred()
  t.after(() => gateGet.resolve())
  const started = []

  app.get('/resource', { concurrency: { max: 1 } }, async () => {
    started.push('GET')
    await gateGet.promise
    return 'get-ok'
  })

  app.post('/resource', { concurrency: { max: 1 } }, async () => {
    started.push('POST')
    return 'post-ok'
  })

  const reqGet = app.inject({ method: 'GET', url: '/resource' })
  await waitFor(() => started.includes('GET'), 500)

  // POST should execute immediately despite GET holding its slot
  const resPost = await app.inject({ method: 'POST', url: '/resource' })
  assert.equal(resPost.statusCode, 200)
  assert.equal(resPost.payload, 'post-ok')
  assert.deepEqual(started, ['GET', 'POST'])

  gateGet.resolve()
  const resGet = await reqGet
  assert.equal(resGet.statusCode, 200)
})

test('request.routeOptions.concurrency exposes the normalized three-field object, or undefined', async () => {
  const app = Fastify()
  const seen = {}

  app.get('/explicit', { concurrency: { max: 2, queueLimit: 5 } }, async request => {
    seen.explicit = request.routeOptions.concurrency
    return 'ok'
  })
  app.get('/plain', async request => {
    seen.plain = request.routeOptions.concurrency
    return 'ok'
  })
  app.register(async function subPlugin (instance) {
    instance.get('/inherited', async request => {
      seen.inherited = request.routeOptions.concurrency
      return 'ok'
    })
    instance.get('/overridden', { concurrency: { max: 7, queueTimeout: 1000 } }, async request => {
      seen.overridden = request.routeOptions.concurrency
      return 'ok'
    })
  }, { prefix: '/sub', concurrency: { max: 3, queueLimit: 10, queueTimeout: 4000 } })

  for (const url of ['/explicit', '/plain', '/sub/inherited', '/sub/overridden']) {
    const res = await app.inject(url)
    assert.equal(res.statusCode, 200, url)
  }

  assert.deepEqual({ ...seen.explicit }, { max: 2, queueLimit: 5, queueTimeout: 30000 })
  assert.deepEqual({ ...seen.inherited }, { max: 3, queueLimit: 10, queueTimeout: 4000 })
  assert.deepEqual({ ...seen.overridden }, { max: 7, queueLimit: 0, queueTimeout: 1000 })
  assert.equal(seen.plain, undefined)
})

test('onRequest hooks do not execute when request is rejected by admission queue', async t => {
  const app = Fastify()
  const gate = deferred()
  t.after(() => gate.resolve())
  const hookCalls = []

  app.get('/hook-check', {
    concurrency: { max: 1, queueLimit: 0 },
    onRequest: async () => {
      hookCalls.push('called')
    }
  }, async () => {
    await gate.promise
    return 'ok'
  })

  const req1 = app.inject('/hook-check')
  await waitFor(() => hookCalls.length === 1, 500)

  // Second request rejected immediately by queueLimit: 0
  const res2 = await expectPrompt(app.inject('/hook-check'), 1000, 'second request to a max:1 queueLimit:0 route')
  assert.equal(res2.statusCode, 503)
  assert.equal(res2.json().code, 'FST_ERR_ROUTE_CONCURRENCY_QUEUE_FULL')
  assert.equal(hookCalls.length, 1, 'onRequest hook must not be invoked for rejected request')

  gate.resolve()
  const res1 = await req1
  assert.equal(res1.statusCode, 200)
})
